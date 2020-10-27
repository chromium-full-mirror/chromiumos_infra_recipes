# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'cros_cache',
    'cros_infra_config',
    'workspace_util',
]


def RunSteps(api):
  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes

  # Configure the builder so that we have
  # self.m.cros_infra_config.gitiles_commit. All of our tests will be with
  # builders that have configs.
  config = api.cros_infra_config.configure_builder(commit=commit,
                                                   changes=changes)
  cache_dir = api.cros_cache.create_cache_dir('temp_cache')
  with api.workspace_util.sync_to_manifest_groups(
      ['group1', 'group2'], manifest_branch="release-R123",
      cache_path_override=cache_dir):
    pass


def GenTests(api):

  yield api.test('basic')