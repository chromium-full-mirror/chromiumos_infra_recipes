# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


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
