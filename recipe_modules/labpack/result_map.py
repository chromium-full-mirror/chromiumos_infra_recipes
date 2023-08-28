# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


def new_result_map():
  """Return an empty result map"""
  return {'ok': True, 'msg': None}


def add_assertion_to_map(m, cond, msg):
  """
  Check if a given condition is true and update the
  failure message string if it is.

  Example Usage:

  >>> m = new_result_map()
  >>> add_assertion_to_map(m, False, "hi")
  {
    "ok": False,
    "msg": "hi",
  }

  Args:
   m     Dictionary with "ok" an "msg" keys
   cond  Anything that can be converted to a Boolean
   msg   A message describing the failure or success

  Returns:
   a map with "ok" and "msg" keys
  """
  if cond:
    return m
  if m['ok']:
    m['ok'] = False
    m['msg'] = msg
  return m
