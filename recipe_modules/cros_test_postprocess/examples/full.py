# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_test_postprocess',
    'recipe_engine/path',
]


def RunSteps(api):
  api.cros_test_postprocess.downloaded_test_result(
      gs_path='gs://a/b', local_path=api.path.mkdtemp())


def GenTests(api):
  yield api.test('basic')
