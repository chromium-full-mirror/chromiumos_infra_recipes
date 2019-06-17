# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Creates a branch using `cros branch create`."""

from PB.chromiumos.branch import Branch
from PB.recipes.chromeos.branch_create import CreateBranchProperties

DEPS = []

PROPERTIES = CreateBranchProperties

def RunSteps(api, properties):
  pass

def GenTests(api):
  yield api.test('test')