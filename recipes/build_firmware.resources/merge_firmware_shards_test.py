#!/usr/bin/env vpython3
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# [VPYTHON:BEGIN]
# python_version: "3.11"
# [VPYTHON:END]

"""Unit tests for merge_firmware_shards.py."""

from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import struct
import tarfile
import tempfile
from typing import Any
import unittest

import merge_firmware_shards

_ACTIVE = (0xFFFF, 0xFF, 0xFF)
_META = 'firmware_metadata.jsonpb'
_NISSA_TAR = 'nissa/firmware_from_source.tar.bz2'


def _write_tar(
    path: Path,
    members: dict[str, bytes],
    dirs: tuple[str, ...] = (),
) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with tarfile.open(path, 'w:bz2') as tar_file:
    for dir_name in dirs:
      dir_info = tarfile.TarInfo(name=dir_name)
      dir_info.type = tarfile.DIRTYPE
      dir_info.mode = 0o755
      tar_file.addfile(dir_info)
    for name, payload in members.items():
      info = tarfile.TarInfo(name=name)
      info.size = len(payload)
      tar_file.addfile(info, io.BytesIO(payload))


def _write_link_tar(
    path: Path,
    member_name: str,
    link_target: str,
    link_type: bytes = tarfile.SYMTYPE,
) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with tarfile.open(path, 'w:bz2') as tar_file:
    info = tarfile.TarInfo(name=member_name)
    info.type = link_type
    info.linkname = link_target
    tar_file.addfile(info)


def _read_tar(path: Path) -> dict[str, bytes]:
  with tarfile.open(path, 'r:bz2') as tar_file:
    result: dict[str, bytes] = {}
    for member in tar_file.getmembers():
      if member.isfile():
        extracted = tar_file.extractfile(member)
        assert extracted is not None
        result[member.name] = extracted.read()
    return result


def _pack_tokens(
    entries: list[tuple[int, str, tuple[int, int, int]]],
) -> bytes:
  head = merge_firmware_shards.PW_HEADER_STRUCT.pack(
      merge_firmware_shards.PW_TOKEN_MAGIC, len(entries))
  body = b''.join(
      merge_firmware_shards.PW_ENTRY_STRUCT.pack(token, day, month, year)
      for token, _, (year, month, day) in entries)
  strings = b''.join(text.encode('utf-8') + b'\x00' for _, text, _ in entries)
  return head + body + strings


def _tar_obj(file_name: str, boards: list[str]) -> dict[str, Any]:
  return {'fileName': file_name, 'tarballInfo': {'type': 'EC', 'board': boards}}


def _make_shard(
    shard_dir: Path,
    shard_index: int,
    target: str,
    boards: list[str],
) -> dict[str, Any]:
  (shard_dir / 'configs' / target).mkdir(parents=True)
  (shard_dir / f'{target}.EC.tar.bz2').write_bytes(target.encode('utf-8'))
  (shard_dir / 'configs' / target / 'ec.cfg').write_text(
      f'C_{target}=y\n', encoding='utf-8')
  _write_tar(shard_dir / _NISSA_TAR,
             {f'{target}/ec.bin': target.encode('utf-8')})
  (shard_dir / 'tokens.bin').write_bytes(
      _pack_tokens([(shard_index + 1, target, _ACTIVE)]))
  token_obj = {'fileName': 'tokens.bin', 'tokenInfo': {'type': 'EC'}}
  objects = [
      _tar_obj(f'{target}.EC.tar.bz2', ['nissa']),
      _tar_obj(_NISSA_TAR, boards),
      token_obj,
  ]
  doc = {
      'bcsVersionInfo': ({
          'versionString': '16852.2.36'
      } if not shard_index else {}),
      'objects': objects,
  }
  (shard_dir / _META).write_text(json.dumps(doc), encoding='utf-8')
  files_by_artifact: dict[str, list[str]] = {
      'FIRMWARE_TARBALL': [f'{target}.EC.tar.bz2', _NISSA_TAR],
      'FIRMWARE_TARBALL_INFO': [_META, f'configs/{target}/ec.cfg'],
      'FIRMWARE_TOKEN_DATABASE': ['tokens.bin'],
  }
  return {
      'build_id': shard_index,
      'shard_dir': str(shard_dir),
      'files_by_artifact': files_by_artifact,
  }


class MergeFirmwareShardsTest(unittest.TestCase):
  """Tests for sharded firmware bundle merging."""

  def setUp(self) -> None:
    super().setUp()
    self.root = Path(tempfile.mkdtemp())
    self.addCleanup(shutil.rmtree, self.root)

  def test_validate_rel_path_rejects_unsafe_inputs(self) -> None:
    unsafe_paths = (
        '',
        '.',
        './',
        './.',
        '../escape.tar.bz2',
        'a/../b',
        '/etc/passwd',
        'a\\b',
    )
    for unsafe in unsafe_paths:
      with self.assertRaises(ValueError,
                             msg=f'Expected rejection for {unsafe!r}'):
        merge_firmware_shards.validate_rel_path(unsafe)
    self.assertEqual(
        merge_firmware_shards.validate_rel_path('./brox/ec.bin').as_posix(),
        'brox/ec.bin',
    )

  def test_tar_merge_collision_and_path_safety(self) -> None:
    tar_one = self.root / '1.tbz'
    tar_two = self.root / '2.tbz'
    _write_tar(
        tar_one,
        {
            'alpha/sub/ec.bin': b'alpha',
            'alpha/cfg': b'A'
        },
        dirs=('.', 'alpha', 'alpha/sub'),
    )
    _write_tar(
        tar_two,
        {
            'gamma/ec.bin': b'gamma',
            'ypsilon/ec.bin': b'ypsilon'
        },
        dirs=('alpha', 'gamma'),
    )
    valid_sym = self.root / 'valid_sym.tbz'
    _write_link_tar(valid_sym, 'alpha/sub/link', '../cfg', tarfile.SYMTYPE)
    valid_hard = self.root / 'valid_hard.tbz'
    _write_link_tar(valid_hard, 'alpha/hard', 'alpha/sub/ec.bin',
                    tarfile.LNKTYPE)
    dest = self.root / 'out' / _NISSA_TAR
    merge_firmware_shards.merge_tar_bz2(
        [tar_one, tar_two, valid_sym, valid_hard], dest)
    expected = {
        'alpha/sub/ec.bin': b'alpha',
        'alpha/cfg': b'A',
        'gamma/ec.bin': b'gamma',
        'ypsilon/ec.bin': b'ypsilon',
    }
    self.assertEqual(_read_tar(dest), expected)

    dup_tar = self.root / 'dup.tbz'
    _write_tar(dup_tar, {'gamma/ec.bin': b'other'})
    with self.assertRaisesRegex(ValueError, 'Duplicate tar member collision'):
      merge_firmware_shards.merge_tar_bz2([tar_two, dup_tar],
                                          self.root / 'err_dup.tbz')

    # Single-source and multi-source escaping symlinks (including ../../s0/...).
    escape_sym_one = self.root / 'esc_outside.tbz'
    _write_link_tar(escape_sym_one, 'model/escape', '../../outside',
                    tarfile.SYMTYPE)
    single_err_dest = self.root / 'single_sym.tbz'
    with self.assertRaisesRegex(ValueError, 'Escaping link'):
      merge_firmware_shards.merge_tar_bz2([escape_sym_one], single_err_dest)
    self.assertFalse(single_err_dest.exists())

    escape_sym_s0 = self.root / 'esc_s0.tbz'
    _write_link_tar(escape_sym_s0, 'model/escape', '../../s0/model',
                    tarfile.SYMTYPE)
    with self.assertRaisesRegex(ValueError, 'Escaping link'):
      merge_firmware_shards.merge_tar_bz2([tar_one, escape_sym_s0],
                                          self.root / 'sym_s0.tbz')

    escape_hard = self.root / 'esc_hard.tbz'
    _write_link_tar(escape_hard, 'model/hard', '../outside', tarfile.LNKTYPE)
    with self.assertRaisesRegex(ValueError, 'Escaping link'):
      merge_firmware_shards.merge_tar_bz2([tar_one, escape_hard],
                                          self.root / 'hard_err.tbz')

    # File-vs-directory collisions in both orders.
    file_first = self.root / 'file_first.tbz'
    nested_second = self.root / 'nested_second.tbz'
    dir_second = self.root / 'dir_second.tbz'
    _write_tar(file_first, {'shared/node': b'file'})
    _write_tar(nested_second, {'shared/node/ec.bin': b'nested'})
    _write_tar(dir_second, {}, dirs=('shared/node',))
    with self.assertRaisesRegex(ValueError, 'Tar file/directory collision'):
      merge_firmware_shards.merge_tar_bz2([file_first, nested_second],
                                          self.root / 'col_fn.tbz')
    with self.assertRaisesRegex(ValueError, 'Tar file/directory collision'):
      merge_firmware_shards.merge_tar_bz2([file_first, dir_second],
                                          self.root / 'col_fd.tbz')
    with self.assertRaisesRegex(ValueError, 'Tar file/directory collision'):
      merge_firmware_shards.merge_tar_bz2([nested_second, file_first],
                                          self.root / 'col_nf.tbz')
    with self.assertRaisesRegex(ValueError, 'Tar file/directory collision'):
      merge_firmware_shards.merge_tar_bz2([dir_second, file_first],
                                          self.root / 'col_df.tbz')

  def test_merge_tokens_bin_preserves_pigweed_binary_format(self) -> None:
    tokens_first = self.root / '1.bin'
    tokens_second = self.root / '2.bin'
    out_tokens = self.root / 'merged.bin'
    entries_first = [
        (0x30, 'z', _ACTIVE),
        (0x10, 'o', (2025, 6, 15)),
        (0x10, 'a', _ACTIVE),
    ]
    entries_second = [
        (0x30, 'z', _ACTIVE),
        (0x10, 'o', _ACTIVE),
        (0x10, 'c', (2026, 1, 2)),
    ]
    tokens_first.write_bytes(_pack_tokens(entries_first))
    tokens_second.write_bytes(_pack_tokens(entries_second))
    merge_firmware_shards.merge_tokens_bin([tokens_first, tokens_second],
                                           out_tokens)
    expected = [
        (0x10, 'a', _ACTIVE),
        (0x10, 'o', _ACTIVE),
        (0x10, 'c', (2026, 1, 2)),
        (0x30, 'z', _ACTIVE),
    ]
    self.assertEqual(
        merge_firmware_shards.parse_tokens_bin(out_tokens.read_bytes()),
        expected,
    )

    bad_magic = self.root / 'bad_magic.bin'
    bad_magic.write_bytes(struct.pack('<8sI4x', b'NOTTOKEN', 0))
    with self.assertRaisesRegex(ValueError, 'Invalid token database magic'):
      merge_firmware_shards.merge_tokens_bin([bad_magic],
                                             self.root / 'err_magic.bin')

    trailing_tokens = self.root / 'trailing.bin'
    trailing_tokens.write_bytes(
        _pack_tokens([(0x10, 'only', _ACTIVE)]) + b'extra\x00')
    with self.assertRaisesRegex(ValueError, 'Unexpected trailing bytes'):
      merge_firmware_shards.parse_tokens_bin(trailing_tokens.read_bytes())

  def test_merge_metadata_jsonpb_conflicts(self) -> None:
    meta_one = self.root / 'meta1.jsonpb'
    meta_two = self.root / 'meta2.jsonpb'
    out_meta = self.root / 'meta_out.jsonpb'

    # Conflicting populated top-level bcsVersionInfo.
    meta_one.write_text(
        json.dumps({
            'bcsVersionInfo': {
                'versionString': '16852.2.36'
            },
            'objects': []
        }),
        encoding='utf-8',
    )
    meta_two.write_text(
        json.dumps({
            'bcsVersionInfo': {
                'versionString': '16852.2.99'
            },
            'objects': []
        }),
        encoding='utf-8',
    )
    with self.assertRaisesRegex(ValueError, 'Conflicting top-level metadata'):
      merge_firmware_shards.merge_metadata_jsonpb([meta_one, meta_two],
                                                  out_meta)

    # Conflicting oneof arm for duplicate fileName.
    meta_one.write_text(
        json.dumps({
            'objects': [{
                'fileName': 'shared.bin',
                'tarballInfo': {
                    'type': 'EC',
                    'board': ['nissa']
                }
            }]
        }),
        encoding='utf-8',
    )
    meta_two.write_text(
        json.dumps({
            'objects': [{
                'fileName': 'shared.bin',
                'configInfo': {
                    'type': 'EC',
                    'board': ['nissa']
                }
            }]
        }),
        encoding='utf-8',
    )
    with self.assertRaisesRegex(ValueError,
                                'Conflicting firmware_object_info kind'):
      merge_firmware_shards.merge_metadata_jsonpb([meta_one, meta_two],
                                                  out_meta)

    # Conflicting non-board field within the same oneof arm.
    meta_two.write_text(
        json.dumps({
            'objects': [{
                'fileName': 'shared.bin',
                'tarballInfo': {
                    'type': 'MAIN',
                    'board': ['fatcat']
                }
            }]
        }),
        encoding='utf-8',
    )
    with self.assertRaisesRegex(ValueError, 'Conflicting tarballInfo metadata'):
      merge_firmware_shards.merge_metadata_jsonpb([meta_one, meta_two],
                                                  out_meta)

  def test_end_to_end_cli_merge_metadata_order_and_conflicts(self) -> None:
    shard_one = _make_shard(self.root / 's1', 0, 'glass', ['nissa', 'fatcat'])
    shard_two = _make_shard(self.root / 's2', 1, 'anrag', ['nissa'])
    spec_path = self.root / 'spec.json'
    out_dir = self.root / 'merged'
    spec_path.write_text(
        json.dumps({
            'output_dir': str(out_dir),
            'shards': [shard_one, shard_two]
        }),
        encoding='utf-8',
    )
    self.assertEqual(
        merge_firmware_shards.main(['--input-json',
                                    str(spec_path)]), 0)
    expected_tar = {'anrag/ec.bin': b'anrag', 'glass/ec.bin': b'glass'}
    self.assertEqual(_read_tar(out_dir / _NISSA_TAR), expected_tar)
    meta = json.loads((out_dir / _META).read_text(encoding='utf-8'))
    self.assertEqual(meta['bcsVersionInfo'], {'versionString': '16852.2.36'})
    expected_names = [
        'anrag.EC.tar.bz2',
        'glass.EC.tar.bz2',
        _NISSA_TAR,
        'tokens.bin',
    ]
    self.assertEqual([obj['fileName'] for obj in meta['objects']],
                     expected_names)
    self.assertEqual(meta['objects'][2]['tarballInfo']['board'],
                     ['nissa', 'fatcat'])

    (self.root / 's2/glass.EC.tar.bz2').write_bytes(b'corrupted')
    shard_two['files_by_artifact']['FIRMWARE_TARBALL'].append(
        'glass.EC.tar.bz2')
    with self.assertRaisesRegex(ValueError, 'Conflicting shard artifact'):
      merge_firmware_shards.merge_shard_bundles(self.root / 'conflict',
                                                [shard_one, shard_two])

  def test_recipe_input_json_dot_sentinel_and_missing_file(self) -> None:
    shard_one = _make_shard(self.root / 's201', 201, 'brox', ['brox'])
    shard_one['files_by_artifact']['FIRMWARE_TARBALL'].append('.')
    merge_firmware_shards.merge_shard_bundles(self.root / 'out', [shard_one])
    self.assertTrue((self.root / 'out/brox.EC.tar.bz2').is_file())

    dot_slash_shard = _make_shard(self.root / 's202', 202, 'brox', ['brox'])
    dot_slash_shard['files_by_artifact']['FIRMWARE_TARBALL'].append('./')
    with self.assertRaisesRegex(ValueError, 'Unsafe relative artifact path'):
      merge_firmware_shards.merge_shard_bundles(self.root / 'out_dotslash',
                                                [dot_slash_shard])

    shard_one['files_by_artifact']['FIRMWARE_TARBALL'].append(
        'missing.EC.tar.bz2')
    with self.assertRaisesRegex(FileNotFoundError, 'Missing shard artifact'):
      merge_firmware_shards.merge_shard_bundles(self.root / 'out2', [shard_one])


if __name__ == '__main__':
  unittest.main()
