# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Define Skylab structs."""

from collections import namedtuple

# Describes a skylab task.
# Fields:
#   id (str): The task ID.
#   test (HwTest): The test running on Skylab.
#   unit (HwTestUnit): The unit the test was specified in.
SkylabTask = namedtuple('SkylabTask', ['id', 'url', 'test', 'unit'])

# Describes a skylab result.
# Fields:
#   task (SkylabTask): The SkylabTask that ran.
#   success (bool): Whether or not the task exited non-zero.
#   child_results (list[WaitTaskResult.Task]): The task result of individual tests within.
SkylabResult = namedtuple('SkylabResult', ['task', 'success', 'child_results'])

# (HwTestUnit, HwTest) tuple
# Fields:
#   unit (HwTestUnit)
#   hw_test (HwTest)
UnitHwTest = namedtuple('UnitHwTest', ['unit', 'hw_test'])