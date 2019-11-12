# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS cache payloads."""

DEPS = [
    'recipe_engine/step',
    'cros_source',
    'repo',
]


def RunSteps(api):
  with api.step.nest('repo checkout'):
    api.repo.init(manifest_url=api.cros_source.INTERNAL_MANIFEST_URL)
    api.repo.sync(jobs=32)


def GenTests(api):
  yield api.test('basic')
