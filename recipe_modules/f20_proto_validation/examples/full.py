# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'f20_proto_validation',
]


def RunSteps(api):
  api.f20_proto_validation.log_sample_metadata()
  api.f20_proto_validation.log_sample_plan()


def GenTests(api):
  yield api.test('basic')
