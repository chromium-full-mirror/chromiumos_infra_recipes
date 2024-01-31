# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Sync values from a source-controlled key-value store to a GS:// file.

Key-value store (KVS) files are simple pairs of key="value", such as:
  my_key="foo"
  your_key="bar"
For new config files, JSON is the preferred standard. However, ChromeOS deals
with a handful of legacy KVSs. For more about the KVS format, see
recipe_modules/key_value_store/ and chromite/utils/key_value_store.py.

This recipe makes a few simplifying assumptions based on its original
requirements:
1.  The source file is always in the ChromeOS source tree.
2.  The destination file is always in Google Cloud Storage.
3.  There is always exactly one source file and exactly one destination file.
4.  The source file should always be read from tip-of-tree: i.e., HEAD on the
    main branch.
It should not be too hard to remove any of these assumptions. If you need to
extend the recipe with additional features, please go ahead!
"""

import base64
import os
import re
from typing import List, Tuple

from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine import result
from PB.recipes.chromeos.sync_key_value_store import KeyPair
from PB.recipes.chromeos.sync_key_value_store import SyncKeyValueStoreProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import InfraFailure
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'depot_tools/gsutil',
    'gitiles',
    'key_value_store',
]


PROPERTIES = SyncKeyValueStoreProperties

# Contents of the source file for testing.
# Note that this technically gets used as `curl` stdout, so it has to be
# base64-encoded bytes.
# There are enough keys to change multiple keys and leave another unmodified,
# plus a fourth key that would have no effect.
TEST_SOURCE_CONTENTS = base64.b64encode(
    b'''first_source_key="first source value"
second_source_key="second source value"
third_source_key="third source value"
fourth_source_key="identical value"''')
# Original contents of the destination file for testing.
TEST_DEST_CONTENTS = '''first_dest_key="first dest value"
second_dest_key="second dest value"
third_dest_key="third dest value"
fourth_dest_key="identical value"'''


def RunSteps(api: RecipeApi,
             properties: SyncKeyValueStoreProperties) -> result.RawResult:
  """Main recipe logic.

  In short, this recipe will:
  1.  Validate arguments to see if we should exit before doing real work.
  2.  Read the original source file and destination file.
  3.  Prepare updated contents for the destination file.
  4.  Quit early if there are no updates to be made.
  5.  Upload the updated contents to the destination URI.
  """
  _validate_properties(api, properties)

  # Read original files.
  source_contents = api.gitiles.get_file(
      properties.source_gitiles_file.host,
      properties.source_gitiles_file.project,
      properties.source_gitiles_file.path,
      ref=properties.source_gitiles_file.ref or None,
      test_output_data=TEST_SOURCE_CONTENTS).decode()
  dest_contents = api.gsutil.cat(
      properties.dest_uri, stdout=api.raw_io.output_text(),
      step_test_data=lambda: api.raw_io.test_api.stream_output_text(
          TEST_DEST_CONTENTS)).stdout

  # Prepare new dest contents, and exit early if no changes made.
  updated_contents = _update_dest_contents(api, source_contents, dest_contents,
                                           properties.key_pairs)
  if updated_contents == dest_contents:
    return result.RawResult(status=common.SUCCESS,
                            summary_markdown='No changes made.')

  # Write the updated contents to Google Storage.
  _upload_contents_to_gs(api, updated_contents, properties.dest_uri,
                         acl=properties.canned_acl_for_upload,
                         dry_run=properties.dry_run)
  return result.RawResult(status=common.SUCCESS)


def _validate_properties(api: RecipeApi,
                         properties: SyncKeyValueStoreProperties) -> None:
  """Ensure that required properties exist and are well-formatted.

  This function occurs before any actual work is done, so it doesn't check
  whether the source and destination files actually exist. It just validates
  that the properties look correct enough to run with.

  Raises:
    InfraFailure: If any required fields are not set.
    InfraFailure: If the source file path is not a relative path.
    InfraFailure: If the dest URI is not a GS:// URI.
  """
  with api.step.nest('validate properties'):
    if not properties.source_gitiles_file.host:
      raise InfraFailure('Source Gitiles file does not specify a host.')
    if not properties.source_gitiles_file.project:
      raise InfraFailure('Source Gitiles file does not specify a project.')
    if not properties.source_gitiles_file.path:
      raise InfraFailure('Source Gitiles file does not specify a path.')
    if os.path.isabs(properties.source_gitiles_file.path):
      raise InfraFailure(
          'Source path is absolute; must be relative to checkout root.')
    if not properties.dest_uri:
      raise InfraFailure('Destination URI not specified.')
    if not properties.dest_uri.startswith('gs://'):
      raise InfraFailure('Destination URI does not look like a gs:// URI.')
    if not properties.key_pairs:
      raise InfraFailure('No key pairs specified.')
    for key_pair in properties.key_pairs:
      if not key_pair.source_key:
        raise InfraFailure('Key pair does not specify a source key.')
      if not key_pair.dest_key:
        raise InfraFailure('Key pair does not specify a dest key.')


def _update_dest_contents(
    api: RecipeApi,
    source_contents: str,
    dest_contents: str,
    key_pairs: List[KeyPair],
) -> str:
  """Create new key-value store contents in-memory with the updated values.

  Note that this function does not actually update the dest file. It only
  creates a new contents string with the updated contents.

  Args:
    api: The recipe API.
    source_contents: The contents of the source key-value store.
    dest_contents: The original contents of the destination key-value store.
    key_pairs: A definition of which values to copy, and where to copy them.

  Returns:
    The contents of an updated key-value store file.

  Raises:
    StepFailure: If any key pair's source key is not found in the source file.
    StepFailure: If any key pair's dest key is not found in the dest file, and
      that key pair does not have append_if_dest_key_missing==True. (This is
      raised during api.key_value_store.update_one_value().)
  """
  with api.step.nest('prepare new dest file contents') as presentation:
    presentation.logs['original source file contents'] = source_contents
    presentation.logs['original dest file contents'] = dest_contents
    source_dict = api.key_value_store.parse_contents(source_contents,
                                                     source='source file')
    dest_dict = api.key_value_store.parse_contents(dest_contents,
                                                   source='dest file')
    for key_pair in key_pairs:
      if key_pair.source_key not in source_dict:
        raise StepFailure(
            f'Source key {key_pair.source_key} not found in source file.')
      if (key_pair.dest_key not in dest_dict and
          not key_pair.append_if_dest_key_missing):
        raise StepFailure(
            f'Dest key {key_pair.dest_key} not found in destination file.')
      old_value = dest_dict.get(key_pair.dest_key, None)
      new_value = source_dict[key_pair.source_key]
      if old_value == new_value:
        continue
      if old_value is not None:
        presentation.properties[f'old_{key_pair.dest_key}'] = old_value
      presentation.properties[f'new_{key_pair.dest_key}'] = new_value
      dest_contents = api.key_value_store.update_one_value(
          dest_contents,
          key_pair.dest_key,
          new_value,
          append_if_missing=key_pair.append_if_dest_key_missing,
      )
    presentation.logs['updated dest file contents'] = dest_contents
  return dest_contents


def _upload_contents_to_gs(api: RecipeApi, contents: str, uri: str,
                           acl: str = '', dry_run: bool = False) -> None:
  """Write a string to a file and upload it to Google Storage.

  Args:
    api: The recipe API.
    contents: The string to write into a file and upload.
    uri: The URI to which the file will be uploaded.
    acl: The canned ACL to set for the uploaded file, if any.
    dry_run: If True, then remote file will not actually be pushed.
  """
  with api.step.nest(f'upload to {uri}') as presentation:
    presentation.logs['contents'] = contents
    temp_file = api.path.mkstemp('dest_file_for_upload')
    api.file.write_text('write temp file', temp_file, contents)
    temp_filepath = api.path.abspath(temp_file)
    args = []
    if acl:
      args.extend(['-a', acl])
    bucket, path = _parse_gsutil_uri(uri)
    api.gsutil.upload(temp_filepath, bucket, path, args=args, dry_run=dry_run)


def _parse_gsutil_uri(uri) -> Tuple[str, str]:
  """Parse a full gsutil URI into the bucket and the path.

  Args:
    uri: A full gsutil URI, such as gs://my-bucket/path/to/file.txt

  Returns:
    A tuple of (bucket, path), where bucket is what comes immediately after
    gs:// and before the next /, and path is everything after that /.
    For example, if uri is 'gs://my-bucket/path/to/file.txt', then the return
    value would be ('my-bucket', 'path/to/file.txt').
  """
  parser = re.compile(r'^gs://(?P<bucket>[^/]+)/(?P<path>.+)$')
  groups = parser.match(uri).groupdict()
  return groups['bucket'], groups['path']


def GenTests(api: RecipeTestApi):
  SAMPLE_GITILES_HOST = 'chromium.googlesource.com'
  SAMPLE_GITILES_PROJECT = 'chromiumos/overlays/chromiumos-overlay'
  SAMPLE_GITILES_PATH = 'chromeos/binhost/host/sdk_version.conf'
  SAMPLE_GITILES_FILE = {
      'host': SAMPLE_GITILES_HOST,
      'project': SAMPLE_GITILES_PROJECT,
      'path': SAMPLE_GITILES_PATH,
  }
  SAMPLE_GS_URI = 'gs://chromiumos-sdk/cros-sdk-latest.conf'
  SAMPLE_KEY_PAIRS = [
      {
          'source_key': 'first_source_key',
          'dest_key': 'first_dest_key',
      },
      {
          'source_key': 'second_source_key',
          'dest_key': 'second_dest_key',
      },
  ]
  SAMPLE_CANNED_ACL = 'public-read'

  yield api.test(
      'basic',
      api.properties(source_gitiles_file=SAMPLE_GITILES_FILE,
                     dest_uri=SAMPLE_GS_URI, key_pairs=SAMPLE_KEY_PAIRS),
      # The destination file's old and new values should be saved as output
      # properties for querying.
      api.post_check(post_process.PropertyEquals, 'old_first_dest_key',
                     'first dest value'),
      api.post_check(post_process.PropertyEquals, 'new_first_dest_key',
                     'first source value'),
      api.post_check(post_process.PropertyEquals, 'old_second_dest_key',
                     'second dest value'),
      api.post_check(post_process.PropertyEquals, 'new_second_dest_key',
                     'second source value'),
      # In the updated destination file, the first and second keys should have
      # updated values (based on properties.key_pairs), but the other keys
      # should retain their original values.
      api.post_check(
          post_process.LogEquals, f'upload to {SAMPLE_GS_URI}', 'contents',
          '\n'.join(('first_dest_key="first source value"',
                     'second_dest_key="second source value"',
                     'third_dest_key="third dest value"',
                     'fourth_dest_key="identical value"'))),
      # Because input properties did not specify a canned acl for upload, the
      # gsutil upload step should not include the `-a` (acl) flag.
      api.post_check(post_process.StepCommandDoesNotContain,
                     f'upload to {SAMPLE_GS_URI}.gsutil upload', ['-a']),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS')

  yield api.test(
      'canned-acl',
      api.properties(source_gitiles_file=SAMPLE_GITILES_FILE,
                     dest_uri=SAMPLE_GS_URI, key_pairs=SAMPLE_KEY_PAIRS,
                     canned_acl_for_upload=SAMPLE_CANNED_ACL),
      api.post_check(post_process.StepCommandContains,
                     f'upload to {SAMPLE_GS_URI}.gsutil upload',
                     ['-a', SAMPLE_CANNED_ACL]),
      api.post_process(post_process.DropExpectation), status='SUCCESS')

  yield api.test(
      'append-if-dest-key-missing',
      api.properties(
          source_gitiles_file=SAMPLE_GITILES_FILE, dest_uri=SAMPLE_GS_URI,
          key_pairs=[{
              'source_key': 'first_source_key',
              'dest_key': 'first_dest_key',
          }, {
              'source_key': 'first_source_key',
              'dest_key': 'surprise_key',
              'append_if_dest_key_missing': True,
          }]),
      api.post_check(
          post_process.LogEquals, f'upload to {SAMPLE_GS_URI}', 'contents',
          '\n'.join(('first_dest_key="first source value"',
                     'second_dest_key="second dest value"',
                     'third_dest_key="third dest value"',
                     'fourth_dest_key="identical value"', '',
                     'surprise_key="first source value"'))),
      api.post_check(post_process.PropertiesContain, 'new_surprise_key'),
      api.post_check(post_process.PropertiesDoNotContain, 'old_surprise_key'),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS',
  )

  yield api.test(
      'no-changes',
      api.properties(
          source_gitiles_file=SAMPLE_GITILES_FILE,
          dest_uri=SAMPLE_GS_URI,
          # In the test source contents, these keys have identical values.
          key_pairs=[{
              'source_key': 'fourth_source_key',
              'dest_key': 'fourth_dest_key',
          }],
      ),
      api.post_check(post_process.SummaryMarkdown, 'No changes made.'),
      api.post_check(post_process.DoesNotRun, f'upload to {SAMPLE_GS_URI}'),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS',
  )

  yield api.test(
      'dry-run',
      api.properties(
          source_gitiles_file=SAMPLE_GITILES_FILE,
          dest_uri=SAMPLE_GS_URI,
          key_pairs=SAMPLE_KEY_PAIRS,
          dry_run=True,
      ),
      api.post_check(post_process.StepCommandEmpty,
                     f'upload to {SAMPLE_GS_URI}.gsutil upload'),
      api.post_process(post_process.DropExpectation),
      status='SUCCESS',
  )

  # Various kinds of malformed input properties.

  yield api.test(
      'source-gitiles-file-has-no-host',
      api.properties(
          source_gitiles_file={
              'project': SAMPLE_GITILES_PROJECT,
              'path': SAMPLE_GITILES_PATH,
          }, dest_uri=SAMPLE_GS_URI, key_pairs=SAMPLE_KEY_PAIRS),
      api.post_check(post_process.StepException, 'validate properties'),
      api.post_check(post_process.SummaryMarkdown,
                     'Source Gitiles file does not specify a host.'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'source-gitiles-file-has-no-project',
      api.properties(
          source_gitiles_file={
              'host': SAMPLE_GITILES_HOST,
              'path': SAMPLE_GITILES_PATH,
          }, dest_uri=SAMPLE_GS_URI, key_pairs=SAMPLE_KEY_PAIRS),
      api.post_check(post_process.StepException, 'validate properties'),
      api.post_check(post_process.SummaryMarkdown,
                     'Source Gitiles file does not specify a project.'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'source-gitiles-file-has-no-path',
      api.properties(
          source_gitiles_file={
              'host': SAMPLE_GITILES_HOST,
              'project': SAMPLE_GITILES_PROJECT,
          }, dest_uri=SAMPLE_GS_URI, key_pairs=SAMPLE_KEY_PAIRS),
      api.post_check(post_process.StepException, 'validate properties'),
      api.post_check(post_process.SummaryMarkdown,
                     'Source Gitiles file does not specify a path.'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'source-path-is-absolute',
      api.properties(
          source_gitiles_file={
              'host': SAMPLE_GITILES_HOST,
              'project': SAMPLE_GITILES_PROJECT,
              'path': '/path/to/file.conf',
          },
          dest_uri=SAMPLE_GS_URI,
          key_pairs=SAMPLE_KEY_PAIRS,
      ), api.post_check(post_process.StepException, 'validate properties'),
      api.post_check(
          post_process.SummaryMarkdown,
          'Source path is absolute; must be relative to checkout root.'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'no-dest-uri',
      api.properties(source_gitiles_file=SAMPLE_GITILES_FILE,
                     key_pairs=SAMPLE_KEY_PAIRS),
      api.post_check(post_process.StepException, 'validate properties'),
      api.post_check(post_process.SummaryMarkdown,
                     'Destination URI not specified.'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'dest-uri-is-not-remote',
      api.properties(source_gitiles_file=SAMPLE_GITILES_FILE,
                     dest_uri='path/to/file.conf', key_pairs=SAMPLE_KEY_PAIRS),
      api.post_check(post_process.StepException, 'validate properties'),
      api.post_check(post_process.SummaryMarkdown,
                     'Destination URI does not look like a gs:// URI.'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'no-key-pairs',
      api.properties(source_gitiles_file=SAMPLE_GITILES_FILE,
                     dest_uri=SAMPLE_GS_URI),
      api.post_check(post_process.StepException, 'validate properties'),
      api.post_check(post_process.SummaryMarkdown, 'No key pairs specified.'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'key-pair-missing-source',
      api.properties(
          source_gitiles_file=SAMPLE_GITILES_FILE, dest_uri=SAMPLE_GS_URI,
          key_pairs=[{
              'source_key': 'my_key',
              'dest_key': 'your_key'
          }, {
              'dest_key': 'oh_no'
          }]), api.post_check(post_process.StepException,
                              'validate properties'),
      api.post_check(post_process.SummaryMarkdown,
                     'Key pair does not specify a source key.'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'key-pair-missing-dest',
      api.properties(
          source_gitiles_file=SAMPLE_GITILES_FILE, dest_uri=SAMPLE_GS_URI,
          key_pairs=[{
              'source_key': 'my_key',
              'dest_key': 'your_key'
          }, {
              'source_key': 'oh_no'
          }]), api.post_check(post_process.StepException,
                              'validate properties'),
      api.post_check(post_process.SummaryMarkdown,
                     'Key pair does not specify a dest key.'),
      api.post_process(post_process.DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'source-key-not-in-source-file',
      api.properties(
          source_gitiles_file=SAMPLE_GITILES_FILE, dest_uri=SAMPLE_GS_URI,
          key_pairs=[{
              'source_key': '404-key-not-found',
              'dest_key': 'first_dest_key'
          }]),
      api.post_check(post_process.StepFailure,
                     'prepare new dest file contents'),
      api.post_check(post_process.SummaryMarkdown,
                     'Source key 404-key-not-found not found in source file.'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'dest-key-not-in-dest-file-no-append',
      api.properties(
          source_gitiles_file=SAMPLE_GITILES_FILE, dest_uri=SAMPLE_GS_URI,
          key_pairs=[{
              'source_key': 'first_source_key',
              'dest_key': '404-key-not-found'
          }]),
      api.post_check(post_process.StepFailure,
                     'prepare new dest file contents'),
      api.post_check(
          post_process.SummaryMarkdown,
          'Dest key 404-key-not-found not found in destination file.'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
