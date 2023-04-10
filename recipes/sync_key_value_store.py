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

import os

from PB.recipes.chromeos.sync_key_value_store import SyncKeyValueStoreProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import InfraFailure
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = SyncKeyValueStoreProperties


def RunSteps(api: RecipeApi, properties: SyncKeyValueStoreProperties) -> None:
  _validate_properties(api, properties)


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
          'source_key': 'first_source_key',
          'dest_key': 'first_dest_key',
      },
  ]

  yield api.test(
      'basic',
      api.properties(source_gitiles_file=SAMPLE_GITILES_FILE,
                     dest_uri=SAMPLE_GS_URI, key_pairs=SAMPLE_KEY_PAIRS),
      api.post_check(post_process.StepSuccess, 'validate properties'),
      status='SUCCESS')

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
