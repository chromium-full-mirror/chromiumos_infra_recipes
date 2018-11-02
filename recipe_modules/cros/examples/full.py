# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros',
]


def RunSteps(api):
  api.cros.set_config()
  _ = api.cros.master_src_path
  api.cros.regen_portage_cache('my_overlay')


def GenTests(api):
  yield api.test('basic')
