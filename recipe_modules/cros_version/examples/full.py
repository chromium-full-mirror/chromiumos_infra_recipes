# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'cros_version',
]


def RunSteps(api):
  v = api.cros_version.Version(99, 1234, 56, 1, 2)
  api.assertions.assertEqual(str(v), 'R99-1234.56.1-2')
  api.assertions.assertEqual(v.buildspec_filename, '99/1234.56.1.xml')

  v = api.cros_version.read_workspace_version()
  api.assertions.assertEqual(str(v), 'R99-1234.56.0-101')

  # The second read gets an empty file.
  api.assertions.assertRaises(ValueError,
                              api.cros_version.read_workspace_version)


def GenTests(api):
  yield (api.test('basic') +  #
         api.step_data('read chromeos_version.sh (2)', api.file.read_raw('')))
