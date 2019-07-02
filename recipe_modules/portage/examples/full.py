# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'portage',
]


def RunSteps(api):
  api.portage.uprev_packages(boards=['a', 'b'])
  api.portage.commit_package_uprevs()
  api.portage.push_package_uprevs(dryrun=True)


def GenTests(api):
  yield api.test('basic')
