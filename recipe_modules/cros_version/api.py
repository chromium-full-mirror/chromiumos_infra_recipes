# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS version numbers."""

import re

from recipe_engine import recipe_api

CHROMEOS_VERSION_PATH = 'src/third_party/chromiumos-overlay/chromeos/config/chromeos_version.sh'

CHROMEOS_VERSION_RE_MAPPING = {
    'chrome_branch': re.compile(r'\bCHROME_BRANCH=(\d+)\b'),
    'build': re.compile(r'\bCHROMEOS_BUILD=(\d+)\b'),
    'branch': re.compile(r'\bCHROMEOS_BRANCH=(\d+)\b'),
    'patch': re.compile(r'\bCHROMEOS_PATCH=(\d+)\b'),
}


class Version(object):
  __slots__ = ('chrome_branch', 'build', 'branch', 'patch', 'rc')

  def __init__(self, chrome_branch, build, branch=0, patch=0, rc=None):
    self.chrome_branch = chrome_branch
    self.build = build
    self.branch = branch
    self.patch = patch
    self.rc = rc

  def __str__(self):
    return 'R%d-%s' % (self.chrome_branch, self.platform_version)

  @property
  def platform_version(self):
    s = '%d.%d.%d' % (self.build, self.branch, self.patch)
    if self.rc is not None:
      s += '-rc%d' % self.rc
    return s

  @property
  def buildspec_filename(self):
    return '%d/%s.xml' % (self.chrome_branch, self.platform_version)


class CrosVersionApi(recipe_api.RecipeApi):
  """A module for steps that manipulate Chrome OS versions."""

  Version = Version

  def read_workspace_version(self):
    """Read the Chrome OS version from the workspace.

    Returns: a Version read from the workspace.

    Raises:
      ValueError: if the version file had unexpected formatting.
    """
    version_path = self.m.cros_source.workspace_path.join(CHROMEOS_VERSION_PATH)
    contents = self.m.file.read_raw(
        'read chromeos_version.sh', version_path,
        test_data=self.test_api.chromeos_version_contents)

    version_args = {}
    for k, regex in CHROMEOS_VERSION_RE_MAPPING.items():
      m = regex.search(contents)
      if m is None:
        raise ValueError(
            'pattern %r did not match chromeos_version.sh' % regex.pattern)
      version_args[k] = int(m.group(1))

    version = Version(**version_args)
    self.m.step.active_result.presentation.step_text = 'version: %s' % version
    return version
