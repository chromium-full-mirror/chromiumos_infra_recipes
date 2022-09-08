# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'portage',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.portage.commit_package_uprevs()
  api.portage.push_package_uprevs(dryrun=True)


def GenTests(api):
  yield api.test('basic')
