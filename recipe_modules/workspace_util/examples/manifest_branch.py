# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'cros_cache',
    'cros_source',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  # Configure the builder so that we have
  # self.m.cros_infra_config.gitiles_commit. All of our tests will be with
  # builders that have configs.
  _ = api.cros_source.configure_builder()
  cache_dir = api.cros_cache.create_cache_dir('temp_cache')
  with api.workspace_util.sync_to_manifest_groups(
      ['group1', 'group2'], manifest_branch="release-R123",
      cache_path_override=cache_dir):
    pass


def GenTests(api):

  yield api.test('basic')
