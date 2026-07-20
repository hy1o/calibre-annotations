#!/usr/bin/env python
# coding: utf-8

from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

import io, json, os, re, unicodedata

from six import text_type as unicode

from calibre_plugins.annotations.reader_app_support import USBReader
from calibre_plugins.annotations.common_utils import AnnotationStruct, BookStruct


class XTEINKReaderApp(USBReader):
    app_name = 'XTEINK'

    SUPPORTS_FETCHING = True

    def get_active_annotations(self):
        """
        Import XTEINK X3/X4 per-book annotation JSON files.
        """
        self._log("%s:get_active_annotations()" % self.app_name)
        annotations_db = self.generate_annotations_db_name(self.app_name_, self.opts.device_name)
        self.create_annotations_table(annotations_db)

        device = self.opts.gui.device_manager.device
        device_files = self._list_device_files()
        json_files = [entry for entry in device_files if entry['path'].lower().endswith('.json')]
        self._log("%s:get_active_annotations() - json files=%d" % (
            self.app_name, len(json_files)))

        imported = 0
        for entry in json_files:
            payload = self._read_json_file(device, entry['path'])
            if not self._is_xteink_annotations_payload(payload):
                continue
            book = payload.get('book', {})
            book_id = self._match_annotation_book(book, entry['path'])
            if book_id is None:
                self._log(" XTEINK annotations skipped: no matching Calibre book for '{0}'".format(entry['path']))
                continue
            imported += self._import_annotation_payload(annotations_db, book_id, entry['path'], payload)

        self._log("%s:get_active_annotations() - imported %d annotations" % (
            self.app_name, imported))

        self.update_timestamp(annotations_db)
        self.commit()

    def _read_json_file(self, device, path):
        if not hasattr(device, 'get_file'):
            self._log("%s:_read_json_file() - connected device does not expose get_file" % self.app_name)
            return None
        buf = io.BytesIO()
        try:
            device.get_file(path, buf)
            raw = buf.getvalue().decode('utf-8', 'replace')
            return json.loads(raw)
        except Exception as e:
            self._log("%s:_read_json_file() - unable to read '%s': %s" % (
                self.app_name, path, e))
            return None

    @staticmethod
    def _is_xteink_annotations_payload(payload):
        return (
            isinstance(payload, dict) and
            payload.get('version') == 2 and
            isinstance(payload.get('book'), dict) and
            isinstance(payload.get('annotations'), list)
        )

    def _match_annotation_book(self, book, annotation_path):
        uuid = book.get('uuid')
        if uuid:
            uuid_key = self._norm_text(uuid)
            book_id = self.installed_books_by_uuid.get(uuid_key)
            if book_id is not None:
                return book_id

        path = book.get('path')
        for candidate in (path, self._annotation_path_to_book_path(annotation_path)):
            if candidate:
                path_key = self._norm_path(candidate)
                book_id = self.installed_books_by_path.get(path_key)
                if book_id is not None:
                    return book_id

        title = self._norm_text(book.get('title'))
        author = self._norm_text(book.get('author'))
        if title and author:
            book_id = self.installed_books_by_title_author.get((title, author))
            if book_id is not None:
                return book_id

        filename = self._norm_text(os.path.splitext(os.path.basename(path or annotation_path))[0])
        if filename:
            book_id = self.installed_books_by_filename.get(filename)
            if book_id is not None:
                return book_id
        return None

    def _import_annotation_payload(self, annotations_db, book_id, annotation_path, payload):
        imported = 0
        annotations = payload.get('annotations') or []
        for index, annotation in enumerate(annotations):
            if not isinstance(annotation, dict):
                continue
            text = annotation.get('text')
            if not text:
                continue

            ann_mi = AnnotationStruct()
            ann_mi.book_id = book_id
            ann_mi.annotation_id = self._annotation_id(annotation_path, annotation, index)
            ann_mi.highlight_color = 'Yellow'
            ann_mi.highlight_text = text
            ann_mi.last_modification = self._annotation_timestamp(annotation)
            ann_mi.location = self._annotation_location(annotation)
            ann_mi.location_sort = self._annotation_location_sort(annotation)

            self.add_to_annotations_db(annotations_db, ann_mi)
            self.update_book_last_annotation(
                self.generate_books_db_name(self.app_name_, self.opts.device_name),
                ann_mi.last_modification,
                book_id)
            imported += 1
        self._log(" XTEINK annotations imported from '{0}': {1}".format(
            annotation_path, imported))
        return imported

    @staticmethod
    def _annotation_id(annotation_path, annotation, index):
        annotation_id = annotation.get('id')
        if annotation_id:
            return "{0}:{1}".format(annotation_path, annotation_id)
        return "{0}:{1}".format(annotation_path, index)

    @staticmethod
    def _annotation_timestamp(annotation):
        for key in ('modified', 'created'):
            value = annotation.get(key)
            if value is not None:
                return value
        return 0

    @staticmethod
    def _annotation_location(annotation):
        label = annotation.get('label')
        if label:
            return label
        start = annotation.get('start') or {}
        spine = start.get('spine')
        page = start.get('page')
        if spine is not None and page is not None:
            return "Spine {0}, page {1}".format(
                XTEINKReaderApp._safe_int(spine) + 1,
                XTEINKReaderApp._safe_int(page) + 1)
        if page is not None:
            return "Page {0}".format(XTEINKReaderApp._safe_int(page) + 1)
        return ''

    @staticmethod
    def _annotation_location_sort(annotation):
        start = annotation.get('start') or {}
        return "%08d%08d%08d%08d" % (
            XTEINKReaderApp._safe_int(start.get('spine')),
            XTEINKReaderApp._safe_int(start.get('page')),
            XTEINKReaderApp._safe_int(start.get('line')),
            XTEINKReaderApp._safe_int(start.get('word')))

    @staticmethod
    def _safe_int(value):
        try:
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def _annotation_path_to_book_path(path):
        base = path
        for suffix in (
                '.annotations.json', '.annotation.json', '.highlights.json',
                '.highlight.json', '.bookmarks.json', '.bookmark.json',
                '.notes.json', '.note.json'):
            if base.lower().endswith(suffix):
                book_path = base[:-len(suffix)]
                if book_path.lower().endswith('.epub'):
                    return book_path
                return book_path + '.epub'
        if base.lower().endswith('.epub.json'):
            return base[:-len('.json')]
        return None

    def _list_device_files(self, root='/'):
        device = self.opts.gui.device_manager.device
        if not hasattr(device, '_http_get_json'):
            self._log("%s:_list_device_files() - connected device does not expose _http_get_json" % self.app_name)
            return []
        files = []
        roots = [root]
        if '/.crosspoint/annotations' not in roots:
            roots.append('/.crosspoint/annotations')
        for scan_root in roots:
            self._collect_device_files(device, scan_root, files, set())
        return files

    def _collect_device_files(self, device, path, files, visited):
        normalized_path = path or '/'
        if normalized_path in visited:
            return
        visited.add(normalized_path)

        try:
            entries = device._http_get_json('/api/files', params={'path': normalized_path})
        except Exception as e:
            self._log("%s:_collect_device_files() - listing '%s' failed: %s" % (
                self.app_name, normalized_path, e))
            return

        if not isinstance(entries, list):
            self._log("%s:_collect_device_files() - listing '%s' returned %s instead of list" % (
                self.app_name, normalized_path, type(entries).__name__))
            return

        for entry in entries:
            name = entry.get('name', '')
            if not name:
                continue
            child_path = self._join_device_path(normalized_path, name)
            if entry.get('isDirectory'):
                self._collect_device_files(device, child_path, files, visited)
            else:
                files.append({
                    'path': child_path,
                    'size': entry.get('size', 0),
                    'is_epub': entry.get('isEpub', False),
                })

    @staticmethod
    def _join_device_path(parent, name):
        if parent in ('', '/'):
            return '/' + name
        return parent.rstrip('/') + '/' + name

    @staticmethod
    def _is_annotation_file(path):
        filename = os.path.basename(path).lower()
        return filename.endswith('.json') and (
            'annotation' in filename or
            'highlight' in filename or
            'bookmark' in filename or
            'note' in filename
        )

    def get_installed_books(self):
        self._log("%s:get_installed_books()" % self.app_name)
        self.installed_books = []
        self.installed_books_by_filename = {}
        self.installed_books_by_path = {}
        self.installed_books_by_title_author = {}
        self.installed_books_by_uuid = {}

        db = self.opts.gui.library_view.model().db
        self.onDeviceIds = set(db.search_getting_ids(
            'ondevice:True', None, sort_results=False, use_virtual_library=False))

        self.books_db = self.generate_books_db_name(self.app_name_, self.opts.device_name)
        installed_books = set([])

        self.create_books_table(self.books_db)

        self.opts.pb.set_label("Getting installed books from %s" % self.app_name)
        self.opts.pb.set_value(0)
        self.opts.pb.set_maximum(len(self.onDeviceIds))

        for book_id in self.onDeviceIds:
            mi = db.get_metadata(book_id, index_is_id=True)
            installed_books.add(book_id)

            book_mi = BookStruct()
            book_mi.active = True
            book_mi.author = ''

            for i, author in enumerate(mi.authors):
                this_author = author.split(', ')
                this_author.reverse()
                book_mi.author += ' '.join(this_author)

                if i < len(mi.authors) - 1:
                    book_mi.author += ' & '

            book_mi.book_id = book_id
            book_mi.reader_app = self.app_name
            book_mi.title = mi.title

            if hasattr(mi, 'author_sort'):
                book_mi.author_sort = mi.author_sort

            if hasattr(mi, 'title_sort'):
                book_mi.title_sort = mi.title_sort
            else:
                book_mi.title_sort = re.sub('^\\s*A\\s+|^\\s*The\\s+|^\\s*An\\s+', '', mi.title).rstrip()

            if hasattr(mi, 'uuid'):
                book_mi.uuid = mi.uuid

            self.add_to_books_db(self.books_db, book_mi)
            self._index_installed_book(book_id, mi)
            self.opts.pb.increment()

        self.update_timestamp(self.books_db)
        self.commit()

        self.installed_books = list(installed_books)

    def _index_installed_book(self, book_id, mi):
        if getattr(mi, 'uuid', None):
            self.installed_books_by_uuid[self._norm_text(mi.uuid)] = book_id
        title = self._norm_text(getattr(mi, 'title', None))
        for author in getattr(mi, 'authors', []) or []:
            author_key = self._norm_text(author)
            if title and author_key:
                self.installed_books_by_title_author[(title, author_key)] = book_id
        for path in self._get_device_paths_from_id(book_id):
            normalized = self._norm_path(path)
            self.installed_books_by_path[normalized] = book_id
            self.installed_books_by_filename[self._norm_text(os.path.splitext(os.path.basename(path))[0])] = book_id
    def _get_device_paths_from_id(self, book_id):
        paths = []
        for view_name in ('memory', 'card_a', 'card_b'):
            view = getattr(self.opts.gui, view_name + '_view', None)
            if view is None:
                continue
            try:
                model = view.model()
                model_paths = model.paths_for_db_ids({book_id}, as_map=True).get(book_id, [])
                paths.extend([record.path for record in model_paths])
            except Exception as e:
                self._log("%s:_get_device_paths_from_id() - unable to read %s path for %s: %s" % (
                    self.app_name, view_name, book_id, e))
        return paths

    @staticmethod
    def _norm_path(path):
        if path is None:
            return ''
        path = unicodedata.normalize('NFC', unicode(path)).replace('\\', '/')
        if not path.startswith('/'):
            path = '/' + path
        return path

    @staticmethod
    def _norm_text(text):
        if text is None:
            return ''
        return unicodedata.normalize('NFC', unicode(text)).strip().lower()

class CrossPointReaderApp(XTEINKReaderApp):
    """
    Compatibility alias for CrossPoint Reader's calibre device plugin.

    Older annotation-plugin builds derive the reader app from the first word of
    the device name, so "CrossPoint Reader" resolves to "CrossPoint".
    """
    app_name = 'CrossPoint'
