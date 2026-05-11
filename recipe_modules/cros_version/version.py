# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS version numbers."""

from functools import total_ordering
import re


# The following regexs are evaluated greedily against strings in order to
# extract a Version instantance. The constructor is called with the lambda
# provided (based upon groups found).
def int_or_none(n):
  return None if n is None else int(n)


def int_or_zero(n):
  return 0 if n is None else int(n)


CHROMEOS_VERSION_STRING_RES = [(
    re.compile(r'^(R(?P<chrome_branch>\d+)-)?(?P<build>\d+)'
               r'\.(?P<branch>\d+)(\.(?P<patch>\d+))?(\-(?P<snapshot>\d+))?$'),
    lambda cls, grps: cls(
        int_or_none(grps['chrome_branch']), int(grps['build']),
        int(grps['branch']), int(grps['patch']), int_or_none(grps['snapshot'])))
                              ]

CHROMEOS_BRANCH_VERSION_STRING_RES = [
    (re.compile(r'^[^.]+(R(?P<chrome_branch>\d+))?-(?P<build>\d+)'
                r'(\.(?P<branch>\d+))?\.B(-(?P<main_name>[-_a-zA-Z.]+))?$'),
     lambda cls, grps: cls(
         int_or_none(grps['chrome_branch']), int(grps['build']),
         int_or_zero(grps['branch']), 0, None))
]


@total_ordering
class Version():
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
          "R88-13505.0.0"

    Returns: A constructed Version, or None.
    """
    for (r, l) in CHROMEOS_VERSION_STRING_RES:
      m = re.match(r, version_string)
      if m:
        return l(cls, m.groupdict())
    return None

  @classmethod
  def from_branch_name(cls, branch_name):
    """Construct a Version from a branch_name.

    Args:
      branch_name (str): The branch name
        This supports the following formats:
          "stabilize-foo-13505.B"
          "stabilize-bar-13505.101.B"
          "release-R88-13505.B"

    Returns: A constructed Version, or None.
    """
    for (r, l) in CHROMEOS_BRANCH_VERSION_STRING_RES:
      m = re.match(r, branch_name)
      if m:
        return l(cls, m.groupdict())
    return None

  def __init__(self, chrome_branch, build, branch=0, patch=0, snapshot=None):
    self.chrome_branch = chrome_branch
    self.build = build
    self.branch = branch
    self.patch = patch
    self.snapshot = snapshot

  @property
  def legacy_version(self):
    return '%s%s' % ('R%d-' % self.milestone if self.milestone else '',
                     self.platform_version)

  def __str__(self):
    version = self.legacy_version
    if self.snapshot is not None:
      version += '-%s' % self.snapshot
    return version

  def __eq__(self, other):
    """Determine if versions are equal, ignoring chrome branch or snapshot."""
    return (self.build == other.build and self.branch == other.branch and
            self.patch == other.patch and self.snapshot == other.snapshot)

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
    if self.patch > other.patch:
      return False

    if self.snapshot is not None or other.snapshot is not None:
      # Released manifest (without snapshot suffix) is older than the snapshot
      # manifests.
      self_snapshot = int_or_zero(self.snapshot)
      other_snapshot = int_or_zero(other.snapshot)
      if self_snapshot < other_snapshot:
        return True
      if self_snapshot > other_snapshot:
        return False

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
  def milestone(self):
    return self.chrome_branch

  @property
  def platform_version(self):
    return '%d.%d.%d' % (self.build, self.branch, self.patch)

  @property
  def buildspec_filename(self):
    return '%d/%s.xml' % (self.chrome_branch, self.platform_version)
