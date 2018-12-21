# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'changes',
    'cros',
    'dev',
]


def RunSteps(api):
  assert api.cros.find_project_path('my/project', 'branch1') == 'src/project'
  api.cros.cherry_pick_changes(api.changes.get_changes())


def GenTests(api):
  yield (api.test('basic') +  #
         api.changes.buildbucket_gerrit_change())
