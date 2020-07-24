# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'repo',
]


def RunSteps(api):
  cwd = api.path['cleanup']
  with api.context(cwd=cwd):
    # diff_manifests_informational calls _find_root().  Use that to cover both
    # cases in one test.
    api.repo.diff_manifests_informational(
        cwd.join('manifest-internal/snapshot-a.xml'),
        cwd.join('manifest-internal/snapshot-b.xml'))


def GenTests(api):
  yield api.test('tests')
