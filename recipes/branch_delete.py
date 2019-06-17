# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deletes a branch using `cros branch delete`."""

from PB.recipes.chromeos.branch_delete import DeleteBranchProperties

DEPS = []

PROPERTIES = DeleteBranchProperties

def RunSteps(api, properties):
  pass

def GenTests(api):
  yield api.test('test')