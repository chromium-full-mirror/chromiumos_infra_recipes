# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Checks a project conforms to its program's constraints."""

from PB.recipes.chromeos.check_project_config import (
    CheckProjectConfigProperties)

PROPERTIES = CheckProjectConfigProperties


def RunSteps(api, properties):
  pass


def GenTests(api):
  yield api.test('basic')
