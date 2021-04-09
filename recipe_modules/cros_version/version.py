# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS version numbers."""

from functools import total_ordering
import re


# The following regexs are evaluated greedily against strings in order to
# extract a Version instantance. The constructor is called with the lambda
# provided (based upon groups found).
def int_or_none(n):
  if n is None:
    return None
  return int(n)


CHROMEOS_VERSION_STRING_RES = [
    (re.compile(r'^(R(?P<chrome_branch>\d+)-)?(?P<build>\d+)'
                r'\.(?P<branch>\d+).(?P<patch>\d)+$'), lambda cls, grps: cls(
                    int_or_none(grps['chrome_branch']), int(grps['build']),
                    int(grps['branch']), int(grps['patch']), None))
]


@total_ordering
class Version(object):
  __slots__ = ('chrome_branch', 'build', 'branch', 'patch', 'snapshot')

  @classmethod
  def from_string(cls, version_string):
    """Construct a Version from a string.

    We should extend for differing representations of the version string as
    they become useful.

    Args:
      version (str): The version string to parse.
        This supports the following formats:
          "13505.0.0"
          "R88.13505.0.0"

    Returns: A constructed Version, or None.
    """
    for (r, l) in CHROMEOS_VERSION_STRING_RES:
      m = re.match(r, version_string)
      if m:
        return l(cls, m.groupdict())
    return None

  def __init__(self, chrome_branch, build, branch=0, patch=0, snapshot=None):
    self.chrome_branch = chrome_branch
    self.build = build
    self.branch = branch
    self.patch = patch
    self.snapshot = snapshot

  def __str__(self):
    version = 'R%d-%s' % (self.chrome_branch, self.platform_version)
    if self.snapshot is not None:
      version += '-%s' % self.snapshot
    return version

  def __eq__(self, other):
    """Determine if versions are equal, ignoring chrome branch or snapshot."""
    return (self.build == other.build and self.branch == other.branch and
            self.patch == other.patch)

  def __lt__(self, other):
    """Find lesser of two versions, ignoring chrome branch or snapshot."""
    if self.build < other.build:
      return True
    if self.build > other.build:
      return False
    if self.branch < other.branch:
      return True
    if self.branch > other.branch:
      return False
    if self.patch < other.patch:
      return True
    return False

  def is_after(self, version):
    """Return whether the workspace is at or after a specific version.

    In general, cros_build_api.has_endpoint should be used, rather than checking
    the workspace version.

    Args:
      version (Version or str): The minumum version.

    Returns:
      (bool): whether our version is at least |version|.
    """
    version = (
        version
        if isinstance(version, Version) else Version.from_string(version))
    return self >= version

  @property
  def platform_version(self):
    return '%d.%d.%d' % (self.build, self.branch, self.patch)

  @property
  def buildspec_filename(self):
    return '%d/%s.xml' % (self.chrome_branch, self.platform_version)
