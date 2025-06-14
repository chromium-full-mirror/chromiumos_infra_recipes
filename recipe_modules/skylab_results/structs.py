# Copyright 2019 The ChromiumOS Authors
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
#   status (common_pb2.Status): Representation of the task status.
#   child_results (list[ExecuteResponse.TaskResult]): The task result of individual tests within.
SkylabResult = namedtuple('SkylabResult', ['task', 'status', 'child_results'])

# (HwTestUnit, HwTest) tuple
# Fields:
#   unit (HwTestUnit)
#   hw_test (HwTest)
UnitHwTest = namedtuple('UnitHwTest', ['unit', 'hw_test'])
