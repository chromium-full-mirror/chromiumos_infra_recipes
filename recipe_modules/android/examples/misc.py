# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'android',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.android.get_latest_build('android-package')
  api.android.write_lkgb('android-package', 'android-version')


def GenTests(api):
  yield api.test('basic')
  yield api.test('write-lkgb-unmodified',
                 api.android.set_write_lkgb_response(modified_files=[]))
