# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Renames a branch using `cros branch rename`."""

from PB.recipes.chromeos.branch_rename import RenameBranchProperties

DEPS = []

PROPERTIES = RenameBranchProperties

def RunSteps(api, properties):
  pass

def GenTests(api):
  yield api.test('test')