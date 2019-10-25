# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for sync stable vesrion for ChromeOS build targets & models."""

from PB.recipes.chromeos.lab_platform.sync_stable_version import \
  SyncStableVersionProperties

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step'
]

PROPERTIES = SyncStableVersionProperties


def fetch_omaha_stable_versions(api, properties):
  """Fetch stable versions based on omama status file.

  Returns:
    TODO(xixuan): A dict contains mapping from (build_target, model) to version
        for all stable_version types (cros, faft, firmware).
  """
  with api.step.nest('fetch omaha stable versions'):
    return {}

def fetch_git_stable_versions(api, properties):
  """Fetch existing stable versions from git file.

  Returns:
    TODO(xixuan): A dict contains mapping from (build_target, model) to version
        for all stable_version types.
  """
  with api.step.nest("fetch git stable versions"):
    return {}

def compare_stable_versions(api, omaha_versions, git_versions):
  """Compare stable_versions between omaha & git.

  Returns:
    TODO(xixuan): A dict contains the different stable_versions.
  """
  with api.step.nest("compare stable versions"):
    return {}

def commit_diff(api, properties, difference):
  """Commit the diff to stable version file on git.

  Returns:
    TODO(xixuan): A string URL refering to the committed CL.
  """
  with api.step.nest("commit new stable versions"):
    return ""

def RunSteps(api, properties):
  omaha_versions = fetch_omaha_stable_versions(api, properties)
  git_versions = fetch_git_stable_versions(api, properties)
  difference = compare_stable_versions(api, omaha_versions, git_versions)
  commit_diff(api, properties, difference)

def GenTests(api):
  yield api.test('basic')