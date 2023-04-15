# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format
from PB.lab.labpack import LabpackInput


def extract_executable_name_from_cipd_path(cipd_path):
  """extract_executable_name_from_cipd_path extracts the name of the executable from a CIPD package path.

  By convention, these are the last component of the path before the '${platform}' component.
  We don't check for the presence of a '${platform}' component here because using
  something like 'linux-amd64' is a valid thing to do locally for testing.

  Args:
    cipd_path: a str that is the path to the cipd executable, with trailing `${package}` suffix.

  Returns str containing just the name of the executable.
  """
  return cipd_path.split('/')[-2]


def catch(f, *args, **kwargs):
  """call f with *args and *kwargs as arguments, catching exceptions.

  Args:
    f: a callable.
    args: positional arguments.
    kwargs: keyword arguments.

  Returns:
    A tuple consisting of the result and the exception that was raised.
    At least one of the elements in the tuple will be None.
  """
  try:
    return (f(*args, **kwargs), None)
  except Exception as e:  # pylint: disable=broad-except # pragma: nocover
    return (None, e)  # pragma: nocover


def jsonify_labpack_input(labpack_input: LabpackInput) -> bytes:
  assert isinstance(
      labpack_input,
      LabpackInput), "labpack_input unexpectedly has type {}".format(
          type(labpack_input))
  out = json_format.MessageToJson(labpack_input)
  out = out.encode("utf-8")
  return out
