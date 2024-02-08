# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to test e2e coverage uploads active version."""

import datetime

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/time',
    'build_menu',
    'code_coverage',
]


def RunSteps(api):
  one_month_ago = (api.time.utcnow() - datetime.timedelta(days=30)).isoformat()
  api.assertions.assertTrue(
      api.code_coverage.upload_active_version(one_month_ago))


def GenTests(api):
  yield api.build_menu.test('basic')
