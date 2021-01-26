# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with CrOS version numbers."""

from functools import total_ordering
import re

from recipe_engine import recipe_api

CHROMEOS_VERSION_PATH = 'src/third_party/chromiumos-overlay/chromeos/config/chromeos_version.sh'

CHROMEOS_VERSION_RE_MAPPING = {
    'chrome_branch': re.compile(r'\bCHROME_BRANCH=(\d+)\b'),
    'build': re.compile(r'\bCHROMEOS_BUILD=(\d+)\b'),
    'branch': re.compile(r'\bCHROMEOS_BRANCH=(\d+)\b'),
    'patch': re.compile(r'\bCHROMEOS_PATCH=(\d+)\b'),
}

# The following regexs are evaluated greedily against strings in order to
# extract a Version instantance. The constructor is called with the lambda
# provided (based upon groups found).
CHROMEOS_VERSION_STRING_RES = [
    (re.compile(r'^(?P<build>\d+)\.(?P<branch>\d+).(?P<patch>\d)+$'),
     lambda cls, grps: cls(None, int(grps['build']), int(grps['branch']),
                           int(grps['patch']), None))
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
          ...

    Returns: A constructed Version, or None.
    """
    for (r, l) in CHROMEOS_VERSION_STRING_RES:
      m = re.match(r, version_string)
      if m:
        return l(cls, m.groupdict())

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

  @property
  def platform_version(self):
    return '%d.%d.%d' % (self.build, self.branch, self.patch)

  @property
  def buildspec_filename(self):
    return '%d/%s.xml' % (self.chrome_branch, self.platform_version)


class CrosVersionApi(recipe_api.RecipeApi):
  """A module for steps that manipulate Chrome OS versions."""

  def __init__(self, properties, *args, **kwargs):
    super(CrosVersionApi, self).__init__(*args, **kwargs)
    self._remove_snapshot_from_version = properties.remove_snapshot_from_version

  Version = Version

  def read_workspace_version(self):
    """Read the Chrome OS version from the workspace.

    Returns: a Version read from the workspace.

    Raises:
      ValueError: if the version file had unexpected formatting.
    """
    with self.m.step.nest('read chromeos version') as presentation:
      version_path = self.m.src_state.workspace_path.join(CHROMEOS_VERSION_PATH)
      contents = self.m.file.read_raw(
          'read chromeos_version.sh', version_path,
          test_data=self.test_api.chromeos_version_contents)

      version_args = {}
      for k, regex in CHROMEOS_VERSION_RE_MAPPING.items():
        m = regex.search(contents)
        if m is None:
          raise ValueError('pattern %r did not match chromeos_version.sh' %
                           regex.pattern)
        version_args[k] = int(m.group(1))

      # This option exists because release builders need to publish artifacts
      # to specific paths (which do not include a -$snapshot suffix on the version).
      if not self._remove_snapshot_from_version:
        with self.m.step.nest('read snapshot') as read_snapshot_step:
          # If there is a snapshot isolate we are running against a custom
          # manifest and there is no snapshot footer for us to read snapshot
          # numbers from. In that case we replace this piece of the version
          # with the isolate hash.
          # TODO(b/156557792): remove isolated support after migration
          version_snapshot = (
              self.m.cros_source.snapshot_isolated_hash or
              self.m.cros_source.snapshot_cas_digest)
          if version_snapshot:
            read_snapshot_step.step_text = 'using snapshot isolate'
          else:
            manifest_path = self.m.src_state.build_manifest.path
            manifest_url = self.m.src_state.build_manifest.url
            with self.m.context(cwd=manifest_path):
              snapshot = self.m.src_state.gitiles_commit.id
              self.m.git.fetch_ref(manifest_url, snapshot)
              version_snapshot = self.m.git_footers.position_num(snapshot)
          version_args['snapshot'] = version_snapshot

      version = Version(**version_args)
      presentation.step_text = 'found version: %s' % version
      return version
