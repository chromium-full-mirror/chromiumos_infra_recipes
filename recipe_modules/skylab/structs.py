# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Define Skylab structs."""

from collections import namedtuple
import json

from google.protobuf import json_format

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
#   child_results (list[WaitTaskResult.Task]): The task result of individual tests within.
SkylabResult = namedtuple('SkylabResult', ['task', 'status', 'child_results'])

# (HwTestUnit, HwTest) tuple
# Fields:
#   unit (HwTestUnit)
#   hw_test (HwTest)
UnitHwTest = namedtuple('UnitHwTest', ['unit', 'hw_test'])


# TODO(b/217973414): Once we don't need to ensure parity between PY2/PY3
# expectation files, remove this function and replace with a vanilla str().
def skylab_task_to_str(st):
  """Cast a SkylabTask to a string in a deterministic way."""
  test = json.dumps(
      json_format.MessageToDict(st.test), separators=(',', ':'), sort_keys=True,
      indent=2)
  unit = json.dumps(
      json_format.MessageToDict(st.unit), separators=(',', ':'), sort_keys=True,
      indent=2)
  return 'SkylabTask(id=%s, test=%s, unit=%s)' % (st.id, test, unit)


# TODO(b/217973414): Once we don't need to ensure parity between PY2/PY3
# expectation files, remove this function and replace with a vanilla str().
def skylab_result_to_str(sr):
  """Cast a SkylabResult to a string in a deterministic way."""
  task = skylab_task_to_str(sr.task)
  status = sr.status
  child_results = [
      json.dumps(
          json_format.MessageToDict(cr), separators=(',', ':'), sort_keys=True,
          indent=2) for cr in sr.child_results
  ]
  return 'SkylabResult(task=%s, status=%s, child_results=%s)' % (task, status,
                                                                 child_results)


# TODO(b/217973414): Once we don't need to ensure parity between PY2/PY3
# expectation files, remove this function and replace with a vanilla str().
def unit_hw_test_to_str(uhwt):
  """Cast a UnitHwTest to a string in a deterministic way."""
  unit = json.dumps(
      json_format.MessageToDict(uhwt.unit), separators=(',', ':'),
      sort_keys=True, indent=2)
  hw_test = json.dumps(
      json_format.MessageToDict(uhwt.hw_test), separators=(',', ':'),
      sort_keys=True, indent=2)
  return 'UnitHwTest(unit=%s, hw_test=%s)' % (unit, hw_test)
