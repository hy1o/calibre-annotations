#!/usr/bin/env python
# coding: utf-8

from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

import glob
import os
import tempfile


STORAGE_PLACEHOLDER = os.path.abspath('/<storage>')


class DeviceCapabilityError(RuntimeError):
    pass


class DeviceDisconnectedError(RuntimeError):
    pass


class MaterializedFile(object):
    def __init__(self, path, cleanup=None):
        self.path = path
        self._cleanup = cleanup

    def __enter__(self):
        return self.path

    def __exit__(self, exc_type, exc, tb):
        self.cleanup()

    def cleanup(self):
        if self._cleanup is not None:
            self._cleanup(self.path)
            self._cleanup = None


class BaseDeviceAdapter(object):
    def __init__(self, device):
        self.device = device

    def close(self):
        pass

    def create_annotations_path(self, mi, device_path=None):
        if not device_path:
            raise DeviceCapabilityError("Calibre did not provide a path for this book on the connected device.")
        base, ext = os.path.splitext(device_path)
        if not ext:
            raise DeviceCapabilityError("Unable to infer annotation path from device path '{0}'.".format(device_path))
        return base + '.bookmark'

    def exists(self, path):
        raise NotImplementedError

    def glob(self, pattern):
        raise NotImplementedError

    def get_storage_paths(self):
        raise NotImplementedError

    def materialize_file(self, path):
        raise NotImplementedError

    def metadata_from_path(self, path):
        return self.device.metadata_from_path(path)

    def resolve_book_path(self, annotation_path, fmts, storage_paths, kindle_formats):
        file_fmts = set(fmts or [])
        book_extensions = file_fmts.intersection(set(kindle_formats))
        for storage in storage_paths:
            book_path = annotation_path.replace(STORAGE_PLACEHOLDER, storage)
            for extension in book_extensions:
                this_fmt = self._with_extension(book_path, extension)
                if self.exists(this_fmt):
                    return this_fmt
        return None

    @staticmethod
    def _with_extension(path, extension):
        base, unused_ext = os.path.splitext(path)
        return base + '.' + extension


class FilesystemDeviceAdapter(BaseDeviceAdapter):
    def create_annotations_path(self, mi, device_path=None):
        creator = getattr(self.device, 'create_annotations_path', None)
        if creator is not None:
            return creator(mi, device_path=device_path)
        return BaseDeviceAdapter.create_annotations_path(self, mi, device_path=device_path)

    def exists(self, path):
        return os.path.exists(path)

    def glob(self, pattern):
        return glob.iglob(pattern)

    def get_storage_paths(self):
        storage = []
        for prefix_name, ebook_dir_name in (
                ('_main_prefix', 'EBOOK_DIR_MAIN'),
                ('_card_a_prefix', 'EBOOK_DIR_CARD_A'),
                ('_card_b_prefix', 'EBOOK_DIR_CARD_B')):
            prefix = getattr(self.device, prefix_name, None)
            ebook_dir = getattr(self.device, ebook_dir_name, '')
            if prefix:
                storage.append(os.path.join(prefix, ebook_dir))
        return storage

    def materialize_file(self, path):
        if not self.exists(path):
            raise DeviceCapabilityError("Device file not found: {0}".format(path))
        return MaterializedFile(path)


class MTPDeviceAdapter(BaseDeviceAdapter):
    def __init__(self, device):
        BaseDeviceAdapter.__init__(self, device)
        self._temp_files = []
        if not hasattr(device, 'filesystem_cache') or not hasattr(device, 'get_file'):
            raise DeviceCapabilityError("The connected MTP device does not expose filesystem_cache/get_file.")

    def close(self):
        for path in list(self._temp_files):
            self._cleanup_temp_file(path)

    def create_annotations_path(self, mi, device_path=None):
        entry = self._find_file(device_path)
        if entry is not None:
            return BaseDeviceAdapter.create_annotations_path(self, mi, device_path=self._path_from_entry(entry))
        return BaseDeviceAdapter.create_annotations_path(self, mi, device_path=self._strip_mtp_id_path(device_path))

    def exists(self, path):
        return self._find_file(path) is not None

    def glob(self, pattern):
        directory, filename = self._split_device_path(pattern)
        prefix, suffix = self._split_simple_glob(filename)
        folder = self._find_file(directory) if directory else None
        entries = []
        if folder is not None:
            entries = getattr(folder, 'files', [])
        elif not directory:
            for storage in self._storages():
                entries.extend(getattr(storage, 'files', []))
        for entry in entries:
            name = getattr(entry, 'name', '')
            if name.startswith(prefix) and name.endswith(suffix):
                yield self._path_from_entry(entry)

    def get_storage_paths(self):
        paths = []
        for storage in self._storages():
            for candidate in (storage.name, '/'.join([storage.name, 'documents']), '/'.join([storage.name, 'Documents'])):
                if candidate not in paths:
                    paths.append(candidate)
        return paths

    def materialize_file(self, path):
        entry = self._find_file(path)
        if entry is None:
            raise DeviceCapabilityError("MTP device file not found: {0}".format(path))
        handle = tempfile.NamedTemporaryFile(prefix='annotations-mtp-', suffix='-' + getattr(entry, 'name', 'file'), delete=False)
        try:
            try:
                self.device.get_file(entry.mtp_id_path, handle)
            except Exception as e:
                raise DeviceDisconnectedError("Unable to retrieve '{0}' from MTP device: {1}".format(path, e))
        finally:
            handle.close()
        self._temp_files.append(handle.name)
        return MaterializedFile(handle.name, cleanup=self._cleanup_temp_file)

    def metadata_from_path(self, path):
        entry = self._find_file(path)
        if entry is None:
            raise DeviceCapabilityError("MTP device file not found: {0}".format(path))
        reader = getattr(self.device, 'read_file_metadata', None)
        if reader is not None:
            return reader(entry)
        with self.materialize_file(path) as local_path:
            return self.device.metadata_from_path(local_path)

    def resolve_book_path(self, annotation_path, fmts, storage_paths, kindle_formats):
        book_extensions = set(fmts or []).intersection(set(kindle_formats))
        candidate = self._strip_storage_placeholder(annotation_path)
        for extension in book_extensions:
            this_fmt = self._with_extension(candidate, extension)
            if self.exists(this_fmt):
                return this_fmt
        return None

    def _cleanup_temp_file(self, path):
        try:
            os.remove(path)
        except OSError:
            pass
        try:
            self._temp_files.remove(path)
        except ValueError:
            pass

    def _find_file(self, path):
        entry = self._resolve_mtp_id_path(path)
        if entry is not None:
            return entry
        relpath = self._strip_storage_placeholder(path)
        if not relpath:
            return None
        parts = [part for part in relpath.replace(os.sep, '/').split('/') if part]
        if not parts:
            return None

        for storage in self._storages():
            storage_parts = [storage.name]
            storage_parts.extend([part for part in getattr(storage, 'full_path', ())[1:]])
            candidates = [parts]
            if parts and parts[0] == storage.name:
                candidates.append(parts[1:])
            for candidate in candidates:
                found = storage.find_path(candidate)
                if found is not None:
                    return found
        return None

    def _path_from_entry(self, entry):
        full_path = getattr(entry, 'full_path', None)
        if full_path:
            return '/'.join(full_path)
        return getattr(entry, 'name')

    def _split_device_path(self, path):
        clean = self._strip_storage_placeholder(path).replace(os.sep, '/')
        return clean.rsplit('/', 1) if '/' in clean else ('', clean)

    def _split_simple_glob(self, filename):
        if '*' not in filename:
            return filename, ''
        prefix, suffix = filename.split('*', 1)
        return prefix, suffix

    def _storages(self):
        cache = self.device.filesystem_cache
        entries = getattr(cache, 'entries', None)
        if entries is not None:
            return list(entries)
        storage_ids = [
            getattr(self.device, '_main_id', None),
            getattr(self.device, '_carda_id', None),
            getattr(self.device, '_cardb_id', None),
        ]
        return [cache.storage(sid) for sid in storage_ids if sid is not None and cache.storage(sid) is not None]

    @staticmethod
    def _strip_storage_placeholder(path):
        if path is None:
            return ''
        path = path.replace(os.sep, '/')
        path = MTPDeviceAdapter._strip_mtp_id_path(path)
        placeholder = STORAGE_PLACEHOLDER.replace(os.sep, '/')
        if path.startswith(placeholder + '/'):
            return path[len(placeholder) + 1:]
        if path.startswith('/'):
            return path[1:]
        return path

    def _resolve_mtp_id_path(self, path):
        if not path or not str(path).startswith('mtp:::'):
            return None
        resolver = getattr(self.device.filesystem_cache, 'resolve_mtp_id_path', None)
        if resolver is None:
            return None
        try:
            return resolver(path)
        except Exception:
            return None

    @staticmethod
    def _strip_mtp_id_path(path):
        if path is None:
            return ''
        marker = ':::'
        if not str(path).startswith('mtp:::'):
            return path
        parts = str(path).split(marker, 2)
        if len(parts) == 3:
            return parts[2]
        return path


def device_adapter_for(device):
    if hasattr(device, 'filesystem_cache') and hasattr(device, 'get_file'):
        return MTPDeviceAdapter(device)
    return FilesystemDeviceAdapter(device)
