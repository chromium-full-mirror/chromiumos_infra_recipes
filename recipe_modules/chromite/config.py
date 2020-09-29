# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import re

from recipe_engine.config import config_item_context, ConfigGroup
from recipe_engine.config import Dict, Single, List, Set

# Regular expression to match branch versions.
#
# Examples:
# - release-R54-8743.B
# - stabilize-8743.B
# - factory-gale-8743.19.B
# - stabilize-8743.25.B
_VERSION_RE = re.compile(r'^.*-(\d+)\.(\d+\.)?B$')


def BaseConfig(CBB_CONFIG=None, CBB_BRANCH=None, CBB_BUILD_NUMBER=None,
               CBB_DEBUG=False, CBB_CLOBBER=False, CBB_BUILDBUCKET_ID=None,
               CBB_MASTER_BUILD_ID=None, CBB_EXTRA_ARGS=None, **_kwargs):
  cgrp = ConfigGroup(
      # Base mapping of repository key to repository name.
      repositories=Dict(value_type=Set(basestring)),

      # Checkout Chromite at this branch. "origin/" will be prepended.
      chromite_branch=Single(basestring, empty_val=CBB_BRANCH or 'master'),

      # Should the Chrome version be supplied to cbuildbot?
      use_chrome_version=Single(bool),

      # Should the CrOS manifest commit message be parsed and added to 'cbuildbot'
      # flags?
      read_cros_manifest=Single(bool),

      # cbuildbot tool flags.
      cbb=ConfigGroup(
          # The Chromite configuration to use.
          config=Single(basestring, empty_val=CBB_CONFIG),

          # If supplied, forward to cbuildbot as '--master-build-id'.
          build_id=Single(basestring, empty_val=CBB_MASTER_BUILD_ID),

          # If supplied, forward to cbuildbot as '--buildnumber'.
          build_number=Single(int, empty_val=CBB_BUILD_NUMBER),

          # If supplied, forward to cbuildbot as '--chrome_version'.
          chrome_version=Single(basestring),

          # If True, add cbuildbot flag: '--debug'.
          debug=Single(bool, empty_val=CBB_DEBUG),

          # If True, add cbuildbot flag: '--clobber'.
          clobber=Single(bool, empty_val=CBB_CLOBBER),

          # The (optional) configuration repository to use.
          config_repo=Single(basestring),

          # If supplied, forward to cbuildbot as '--buildbucket-id'
          buildbucket_id=Single(basestring, empty_val=CBB_BUILDBUCKET_ID),

          # Extra arguments passed to cbuildbot.
          extra_args=List(basestring),
      ),

      # If "chromite_branch" includes a branch version, this will be set to the
      # version value. Otherwise, this will be None.
      #
      # Set in "base".
      branch_version=Single(int),

      # If true, the canary version of goma is used instead of the stable version.
      use_goma_canary=Single(bool),
  )

  if CBB_EXTRA_ARGS:
    cgrp.cbb.extra_args = CBB_EXTRA_ARGS
  return cgrp


config_ctx = config_item_context(BaseConfig)


@config_ctx()
def base(c):
  c.repositories['tryjob'] = []
  c.repositories['chromium'] = []
  c.repositories['cros_manifest'] = []

  # Determine if we're manually specifying the tryjob branch in the extra
  # args. If we are, use that as the branch version.
  chromite_branch = c.chromite_branch
  for idx, arg in enumerate(c.cbb.extra_args):
    if arg == '--branch':
      # Two-argument form: "--branch master"
      idx += 1
      if idx < len(c.cbb.extra_args):
        chromite_branch = c.cbb.extra_args[idx]
        break

    # One-argument form: "--branch=master"
    branch_flag = '--branch'
    if arg.startswith(branch_flag):
      chromite_branch = arg[len(branch_flag):]
      break

  # Resolve branch version, if available.
  assert c.chromite_branch, "A Chromite branch must be configured."
  version = _VERSION_RE.match(chromite_branch)
  if version:
    c.branch_version = int(version.group(1))

  # If running on a testing slave, enable "--debug" so Chromite doesn't cause
  # actual production effects.
  if 'TESTING_MASTER_HOST' in os.environ:  # pragma: no cover
    c.cbb.debug = True


@config_ctx(includes=['base'])
def cros(_):
  """Base configuration for CrOS builders to inherit from."""
  pass


@config_ctx(includes=['cros'])
def external(c):
  c.repositories['tryjob'].extend([
      'https://chromium.googlesource.com/chromiumos/tryjobs',
      'https://chrome-internal.googlesource.com/chromeos/tryjobs',
  ])
  c.repositories['chromium'].append(
      'https://chromium.googlesource.com/chromium/src')
  c.repositories['cros_manifest'].append(
      'https://chromium.googlesource.com/chromiumos/manifest-versions')


@config_ctx(group='master', includes=['external'])
def master_swarming(_):
  pass


@config_ctx(group='master', includes=['external'])
def master_chromiumos_chromium(c):
  c.use_chrome_version = True


@config_ctx(group='master', includes=['external'])
def master_chromiumos(_):
  pass


@config_ctx(group='master', includes=['external'])
def master_chromiumos_tryserver(_):
  pass


@config_ctx(includes=['master_chromiumos'])
def chromiumos_coverage(c):
  c.use_chrome_version = True
  c.cbb.config_repo = 'https://example.com/repo.git'


@config_ctx()
def use_goma_canary(c):
  c.use_goma_canary = True
