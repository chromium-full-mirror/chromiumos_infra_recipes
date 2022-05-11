# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
import six

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
               CBB_MAIN_BUILD_ID=None, CBB_EXTRA_ARGS=None, **_kwargs):
  cgrp = ConfigGroup(
      # Base mapping of repository key to repository name.
      repositories=Dict(value_type=Set(six.string_types[0])),

      # Checkout Chromite at this branch. "origin/" will be prepended.
      chromite_branch=Single(six.string_types[0], empty_val=CBB_BRANCH or
                             'main'),

      # Should the Chrome version be supplied to cbuildbot?
      use_chrome_version=Single(bool),

      # Should the CrOS manifest commit message be parsed and added to 'cbuildbot'
      # flags?
      read_cros_manifest=Single(bool),

      # cbuildbot tool flags.
      cbb=ConfigGroup(
          # The Chromite configuration to use.
          config=Single(six.string_types[0], empty_val=CBB_CONFIG),

          # If supplied, forward to cbuildbot as '--master-build-id'.
          build_id=Single(six.string_types[0], empty_val=CBB_MAIN_BUILD_ID),

          # If supplied, forward to cbuildbot as '--buildnumber'.
          build_number=Single(int, empty_val=CBB_BUILD_NUMBER),

          # If supplied, forward to cbuildbot as '--chrome_version'.
          chrome_version=Single(six.string_types[0]),

          # If True, add cbuildbot flag: '--debug'.
          debug=Single(bool, empty_val=CBB_DEBUG),

          # If True, add cbuildbot flag: '--clobber'.
          clobber=Single(bool, empty_val=CBB_CLOBBER),

          # The (optional) configuration repository to use.
          config_repo=Single(six.string_types[0]),

          # If supplied, forward to cbuildbot as '--buildbucket-id'
          buildbucket_id=Single(six.string_types[0],
                                empty_val=CBB_BUILDBUCKET_ID),

          # Extra arguments passed to cbuildbot.
          extra_args=List(six.string_types[0]),
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

  # Resolve branch version, if available.
  assert c.chromite_branch, "A Chromite branch must be configured."


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


@config_ctx(group='main', includes=['external'])
def main_swarming(_):
  pass


@config_ctx(group='main', includes=['external'])
def main_chromiumos(_):
  pass


@config_ctx(includes=['main_chromiumos'])
def chromiumos_coverage(c):
  c.use_chrome_version = True
  c.cbb.config_repo = 'https://example.com/repo.git'
