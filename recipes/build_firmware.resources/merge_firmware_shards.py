#!/usr/bin/env vpython3
# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# [VPYTHON:BEGIN]
# python_version: "3.11"
# [VPYTHON:END]

"""Merges sharded firmware artifact bundles into a single release bundle.

Combines worker-shard output directories produced by sharded Zephyr firmware
builds into a unified bundle directory on coordinator shard 0. Per-board
`firmware_from_source.tar.bz2` archives are streamed and merged without member
collisions, Pigweed `tokens.bin` databases are merged in canonical token order,
`firmware_metadata.jsonpb` manifests are deduplicated with unioned board lists,
and unique per-target tarballs and config files are hardlinked or copied.

The input JSON has these keys:
  output_dir: Path to the destination directory for merged artifacts.
  shards: A list of dicts, each with `shard_dir` (path to a worker shard's
    downloaded artifact directory) and `files_by_artifact` (mapping of artifact
    type name to lists of relative POSIX file paths within `shard_dir`).
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from concurrent import futures
import copy
import datetime
import filecmp
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import sys
import tarfile
from typing import Any

PW_TOKEN_MAGIC = b'TOKENS\x00\x00'
PW_HEADER_STRUCT = struct.Struct('<8sI4x')
PW_ENTRY_STRUCT = struct.Struct('<IBBH')
_NO_REMOVAL_DATE = (0xFFFF, 0xFF, 0xFF)
_OBJECT_INFO_ONEOF_KEYS = (
    'tarballInfo',
    'lcovInfo',
    'coverageHtml',
    'tokenInfo',
    'configInfo',
)
_BOARD_LIST_ONEOF_KEYS = ('tarballInfo', 'configInfo')


def validate_rel_path(rel_path: str) -> PurePosixPath:
  """Validates that `rel_path` is a safe non-empty relative POSIX path.

  Args:
    rel_path: Candidate archive-relative or bundle-relative path string.

  Returns:
    Normalized `PurePosixPath` for `rel_path`.

  Raises:
    ValueError: If `rel_path` is empty, resolves to `.`, contains backslashes,
      is absolute, or traverses parent directories (`..`).
  """
  posix_path = PurePosixPath(rel_path)
  if (not posix_path.parts or '\\' in rel_path or posix_path.is_absolute() or
      '..' in posix_path.parts):
    raise ValueError(f'Unsafe relative artifact path: {rel_path!r}')
  return posix_path


def _validate_tar_link_target(
    member_path: PurePosixPath,
    link_name: str,
    is_symlink: bool,
    src_tar: Path,
) -> None:
  """Validates lexically that a tar link target stays within the archive root.

  Args:
    member_path: Normalized relative path of the symlink or hardlink member.
    link_name: Raw `TarInfo.linkname` value.
    is_symlink: True for a symbolic link (resolved relative to `member_path`'s
      parent directory), False for a hardlink (resolved relative to archive
      root).
    src_tar: Source archive path for error context.

  Raises:
    ValueError: If `link_name` is empty, contains backslashes, is absolute, or
      escapes the archive root at any path component.
  """
  if not link_name or '\\' in link_name:
    raise ValueError(
        f'Escaping link {member_path.as_posix()!r} -> {link_name!r} in '
        f'{src_tar}')
  link_posix = PurePosixPath(link_name)
  if link_posix.is_absolute():
    raise ValueError(
        f'Escaping link {member_path.as_posix()!r} -> {link_name!r} in '
        f'{src_tar}')
  resolved = list(member_path.parent.parts) if is_symlink else []
  for part in link_posix.parts:
    if part in ('', '.'):
      continue
    if part == '..':
      if not resolved:
        raise ValueError(
            f'Escaping link {member_path.as_posix()!r} -> {link_name!r} in '
            f'{src_tar}')
      resolved.pop()
    else:
      resolved.append(part)
  if not resolved:
    raise ValueError(
        f'Escaping link {member_path.as_posix()!r} -> {link_name!r} in '
        f'{src_tar}')


def link_or_copy(src: Path, dest: Path) -> None:
  """Hardlinks `src` to `dest`, falling back to `shutil.copyfile`.

  Args:
    src: Existing source file path.
    dest: Destination file path to create or overwrite.

  Raises:
    OSError: If creating parent directories or copying `src` to `dest` fails.
  """
  dest.parent.mkdir(parents=True, exist_ok=True)
  dest.unlink(missing_ok=True)
  try:
    os.link(src, dest)
  except OSError:
    shutil.copyfile(src, dest)


def parse_tokens_bin(
    data: bytes,
) -> list[tuple[int, str, tuple[int, int, int]]]:
  """Parses a Pigweed binary token database (`pw_tokenizer.tokens`).

  Args:
    data: Raw bytes of a Pigweed binary token database file.

  Returns:
    List of `(token, text, (year, month, day))` tuples in file order.

  Raises:
    ValueError: If the header magic or entry count is invalid, a string entry
      lacks a NUL terminator, or trailing bytes follow the string table.
  """
  header_size = PW_HEADER_STRUCT.size
  entry_size = PW_ENTRY_STRUCT.size
  if len(data) < header_size:
    raise ValueError(f'Token database too short ({len(data)} bytes)')
  magic, count = PW_HEADER_STRUCT.unpack_from(data, 0)
  if magic != PW_TOKEN_MAGIC or count > (len(data) - header_size) // entry_size:
    raise ValueError(f'Invalid token database magic {magic!r} or count {count}')
  entry_offset = header_size
  str_offset = header_size + count * entry_size
  parsed: list[tuple[int, str, tuple[int, int, int]]] = []
  for _ in range(count):
    token, day, month, year = PW_ENTRY_STRUCT.unpack_from(data, entry_offset)
    entry_offset += entry_size
    try:
      removal_date = (datetime.date(year, month, day).year, month, day)
    except ValueError:
      removal_date = _NO_REMOVAL_DATE
    nul_index = data.find(b'\x00', str_offset)
    if nul_index < 0:
      raise ValueError('Unterminated string in Pigweed token string table')
    text = data[str_offset:nul_index].decode('utf-8', 'surrogateescape')
    parsed.append((token, text, removal_date))
    str_offset = nul_index + 1
  if str_offset != len(data):
    raise ValueError(f'Unexpected trailing bytes in token database '
                     f'({len(data) - str_offset} bytes after string table)')
  return parsed


def merge_tokens_bin(sources: Sequence[Path], dest: Path) -> None:
  """Merges Pigweed `tokens.bin` databases in canonical `pw_tokenizer` order.

  Args:
    sources: Input `tokens.bin` paths to merge.
    dest: Output `tokens.bin` path to write.

  Raises:
    ValueError: If any input file is not a valid Pigweed binary token database.
    OSError: If reading an input file or writing `dest` fails.
  """
  entries: dict[tuple[int, str], tuple[int, int, int]] = {}
  for src in sources:
    for token, text, removal_date in parse_tokens_bin(src.read_bytes()):
      key = (token, text)
      if key not in entries or removal_date > entries[key]:
        entries[key] = removal_date
  ordered = sorted(
      entries.items(),
      key=lambda item: (
          item[0][0],
          tuple(-part for part in item[1]),
          item[0][1],
      ),
  )
  dest.parent.mkdir(parents=True, exist_ok=True)
  strings = bytearray()
  with dest.open('wb') as out_file:
    out_file.write(PW_HEADER_STRUCT.pack(PW_TOKEN_MAGIC, len(ordered)))
    for (token, text), (year, month, day) in ordered:
      out_file.write(PW_ENTRY_STRUCT.pack(token, day, month, year))
      strings += text.encode('utf-8', 'surrogateescape') + b'\x00'
    out_file.write(strings)


def _extract_object_oneof_kind(
    obj: Mapping[str, Any],
    file_name: str,
) -> str | None:
  """Returns the single camelCase `firmware_object_info` oneof key on `obj`."""
  present = [key for key in _OBJECT_INFO_ONEOF_KEYS if key in obj]
  if len(present) > 1:
    raise ValueError(
        f'Multiple firmware_object_info fields on {file_name!r}: {present}')
  return present[0] if present else None


def _merge_object_info(
    current: dict[str, Any],
    incoming: Mapping[str, Any],
    file_name: str,
) -> None:
  """Merges `incoming` ObjectInfo into `current`, unioning `board` lists."""
  current_kind = _extract_object_oneof_kind(current, file_name)
  incoming_kind = _extract_object_oneof_kind(incoming, file_name)
  if current_kind != incoming_kind:
    raise ValueError(
        f'Conflicting firmware_object_info kind for {file_name!r}: '
        f'{current_kind!r} != {incoming_kind!r}')
  current_outer = {
      key: value for key, value in current.items() if key != current_kind
  }
  incoming_outer = {
      key: value for key, value in incoming.items() if key != incoming_kind
  }
  if current_outer != incoming_outer:
    raise ValueError(
        f'Conflicting top-level ObjectInfo fields for {file_name!r}: '
        f'{current_outer!r} != {incoming_outer!r}')
  if current_kind is None:
    return
  if current_kind in _BOARD_LIST_ONEOF_KEYS:
    current_meta = {
        key: value
        for key, value in current[current_kind].items()
        if key != 'board'
    }
    incoming_meta = {
        key: value
        for key, value in incoming[current_kind].items()
        if key != 'board'
    }
    if current_meta != incoming_meta:
      raise ValueError(
          f'Conflicting {current_kind} metadata for {file_name!r}: '
          f'{current_meta!r} != {incoming_meta!r}')
    merged_boards = list(
        dict.fromkeys([
            *(current[current_kind].get('board') or []),
            *(incoming[current_kind].get('board') or []),
        ]))
    if (merged_boards or 'board' in current[current_kind] or
        'board' in incoming[current_kind]):
      current[current_kind]['board'] = merged_boards
  elif current[current_kind] != incoming[current_kind]:
    raise ValueError(f'Conflicting {current_kind} metadata for {file_name!r}: '
                     f'{current[current_kind]!r} != {incoming[current_kind]!r}')


def merge_metadata_jsonpb(sources: Sequence[Path], dest: Path) -> None:
  """Merges shard `FirmwareArtifactInfo` JSONPB files, deduplicating objects.

  Args:
    sources: Input `firmware_metadata.jsonpb` paths to merge.
    dest: Output `firmware_metadata.jsonpb` path to write.

  Raises:
    ValueError: If populated top-level metadata fields conflict across shards,
      or if duplicate `fileName` objects disagree on their `oneof` kind or
      non-`board` metadata fields.
    OSError: If reading an input file or writing `dest` fails.
  """
  top_fields: dict[str, Any] = {}
  objects_by_name: dict[str, dict[str, Any]] = {}
  for src in sources:
    doc = json.loads(src.read_text(encoding='utf-8'))
    for key, value in doc.items():
      if key == 'objects':
        continue
      if key not in top_fields or (not top_fields[key] and value):
        top_fields[key] = copy.deepcopy(value)
      elif top_fields[key] and value and top_fields[key] != value:
        raise ValueError(f'Conflicting top-level metadata field {key!r}: '
                         f'{top_fields[key]!r} != {value!r}')
    for obj in doc.get('objects', []):
      file_name = obj.get('fileName')
      if not file_name:
        continue
      _extract_object_oneof_kind(obj, file_name)
      if file_name not in objects_by_name:
        objects_by_name[file_name] = copy.deepcopy(obj)
      else:
        _merge_object_info(objects_by_name[file_name], obj, file_name)
  rank = {'tokens.bin': 2, 'firmware_from_source.tar.bz2': 1}
  ordered_objects = sorted(
      objects_by_name.items(),
      key=lambda item: (rank.get(PurePosixPath(item[0]).name, 0), item[0]),
  )
  top_fields['objects'] = [obj for _, obj in ordered_objects]
  dest.parent.mkdir(parents=True, exist_ok=True)
  dest.write_text(json.dumps(top_fields, indent=2) + '\n', encoding='utf-8')


def merge_tar_bz2(sources: Sequence[Path], dest: Path) -> None:
  """Streams and merges `.tar.bz2` board archives into `dest` safely.

  Validates every archive member path and link target lexically against the
  archive root before writing to `dest`, including when `len(sources) == 1`.

  Args:
    sources: Input `.tar.bz2` archive paths to merge in order.
    dest: Output `.tar.bz2` archive path to write.

  Raises:
    ValueError: If any archive contains unsafe member paths, escaping symlinks
      or hardlinks, unsupported member types, duplicate non-directory entries,
      or file-versus-directory collisions across shards.
    tarfile.TarError: If reading or writing a `.tar.bz2` stream fails.
    OSError: If opening `sources` or creating `dest` fails.
  """
  dest.parent.mkdir(parents=True, exist_ok=True)
  seen_files: set[str] = set()
  seen_dirs: set[str] = set()
  emitted_dirs: set[str] = set()
  try:
    with tarfile.open(dest, 'w:bz2') as dest_tar:
      for src_tar in sources:
        with tarfile.open(src_tar, 'r:bz2') as src_archive:
          for member in src_archive:
            raw_posix = PurePosixPath(member.name)
            if (not raw_posix.parts and member.isdir() and
                '\\' not in member.name and not raw_posix.is_absolute()):
              continue
            rel_path = validate_rel_path(member.name)
            norm_name = rel_path.as_posix()
            ancestors = [
                parent.as_posix() for parent in rel_path.parents if parent.parts
            ]
            if member.isdir():
              if norm_name in seen_files:
                raise ValueError(f'Tar file/directory collision at {norm_name}')
              for ancestor in ancestors:
                if ancestor in seen_files:
                  raise ValueError(
                      f'Tar file/directory collision at {ancestor}')
              seen_dirs.add(norm_name)
              seen_dirs.update(ancestors)
              if norm_name in emitted_dirs:
                continue
              emitted_dirs.add(norm_name)
              member_copy = copy.copy(member)
              member_copy.name = norm_name
              dest_tar.addfile(member_copy)
              continue

            if not (member.isfile() or member.issym() or member.islnk()):
              raise ValueError(
                  f'Unsupported tar member type for {norm_name!r} in {src_tar}')
            if member.issym() or member.islnk():
              _validate_tar_link_target(
                  rel_path,
                  member.linkname,
                  is_symlink=member.issym(),
                  src_tar=src_tar,
              )
            if norm_name in seen_files:
              raise ValueError(f'Duplicate tar member collision at {norm_name}')
            if norm_name in seen_dirs:
              raise ValueError(f'Tar file/directory collision at {norm_name}')
            for ancestor in ancestors:
              if ancestor in seen_files:
                raise ValueError(f'Tar file/directory collision at {ancestor}')
            seen_files.add(norm_name)
            seen_dirs.update(ancestors)
            member_copy = copy.copy(member)
            member_copy.name = norm_name
            if member.isfile():
              payload_stream = src_archive.extractfile(member)
              dest_tar.addfile(member_copy, fileobj=payload_stream)
            else:
              dest_tar.addfile(member_copy)
  except Exception:
    dest.unlink(missing_ok=True)
    raise


def merge_shard_bundles(
    output_dir: Path,
    shards: Iterable[Mapping[str, Any]],
    max_workers: int | None = None,
) -> None:
  """Merges all shard directories described by `shards` into `output_dir`.

  Args:
    output_dir: Destination directory for the merged firmware bundle.
    shards: Iterable of shard descriptor mappings, each containing `shard_dir`
      and `files_by_artifact`.
    max_workers: Optional cap on worker threads used for parallel board tarball
      merging.

  Raises:
    FileNotFoundError: If any declared shard artifact path does not exist on
      disk under its `shard_dir`.
    ValueError: If any artifact path is unsafe, if non-mergeable duplicate
      artifacts differ in content across shards, or if merging a board archive,
      token database, or metadata manifest fails validation.
  """
  output_dir.mkdir(parents=True, exist_ok=True)
  by_rel: dict[str, list[Path]] = {}
  for shard in shards:
    shard_dir = Path(shard['shard_dir'])
    seen: set[str] = set()
    for rel_paths in shard.get('files_by_artifact', {}).values():
      for rel_path in rel_paths:
        if rel_path == '.':
          continue
        norm_path = validate_rel_path(rel_path).as_posix()
        if norm_path in seen:
          continue
        seen.add(norm_path)
        src_file = shard_dir / norm_path
        if not src_file.is_file():
          raise FileNotFoundError(f'Missing shard artifact {src_file}')
        by_rel.setdefault(norm_path, []).append(src_file)

  tar_tasks: list[tuple[Sequence[Path], Path]] = []
  for rel_path, sources in sorted(by_rel.items()):
    dest = output_dir / rel_path
    artifact_name = PurePosixPath(rel_path).name
    if artifact_name == 'firmware_metadata.jsonpb':
      merge_metadata_jsonpb(sources, dest)
    elif artifact_name == 'tokens.bin':
      merge_tokens_bin(sources, dest)
    elif artifact_name == 'firmware_from_source.tar.bz2':
      tar_tasks.append((sources, dest))
    elif any(not filecmp.cmp(sources[0], other_src, shallow=False)
             for other_src in sources[1:]):
      raise ValueError(f'Conflicting shard artifact {rel_path!r}')
    else:
      link_or_copy(sources[0], dest)

  if tar_tasks:
    workers = max(1, min(len(tar_tasks), max_workers or (os.cpu_count() or 4)))
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
      list(pool.map(lambda task: merge_tar_bz2(*task), tar_tasks))


def get_parser() -> argparse.ArgumentParser:
  """Builds the CLI argument parser for `merge_firmware_shards`.

  Returns:
    Configured `argparse.ArgumentParser` accepting `--input-json`.
  """
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
      '--input-json',
      required=True,
      type=Path,
      help='Path to the input JSON file describing output_dir and shards.',
  )
  return parser


def main(argv: Sequence[str] | None = None) -> int:
  """Parses CLI flags and merges sharded firmware artifact bundles.

  Args:
    argv: Optional list of CLI arguments (defaults to `sys.argv[1:]`).

  Returns:
    Exit code `0` on success.

  Raises:
    FileNotFoundError: If `--input-json` or a declared shard file is missing.
    ValueError: If input paths, metadata, tokens, or tar archives are invalid.
  """
  parser = get_parser()
  opts = parser.parse_args(argv)
  spec = json.loads(opts.input_json.read_text(encoding='utf-8'))
  merge_shard_bundles(Path(spec['output_dir']), spec['shards'])
  return 0


if __name__ == '__main__':
  sys.exit(main())
