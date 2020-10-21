# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['cros_paygen']


def RunSteps(api):
  # TODO(crbug.com/1122854): Impl
  api.cros_paygen.get_request(None, [], [])


def GenTests(api):
  yield api.test('basic')
