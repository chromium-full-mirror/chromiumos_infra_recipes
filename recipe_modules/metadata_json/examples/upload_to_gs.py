# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_infra_config',
    'metadata_json',
]

from PB.chromiumos.common import BuildTarget


def RunSteps(api):
  api.metadata_json.add_default_entries()
  config = api.cros_infra_config.config
  bt = BuildTarget(name='amd64-generic')
  api.metadata_json.upload_to_gs(config, bt, partial=True)


def GenTests(api):
  yield api.test('basic', api.metadata_json.test_builder(cq=True))
