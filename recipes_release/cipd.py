#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Code for interacting with CIPD."""

import string
import subprocess
from typing import Optional
from typing import Tuple

import common


PACKAGE_NAME = "infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes"


def _cipd_ref_to_instance_id(ref: common.CipdRef) -> common.CipdInstance:
  """Find the instanceid associated with a recipes CIPD ref.

  Sample `cipd resolve` output:
  Packages:
  infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes:jSHBVU-ZzC8Pbi2hlc0r89wukZBQ9EYZKK7TX1zmboIC
  """
  p = subprocess.run(['cipd', 'resolve', '-version', ref, common.RECIPE_BUNDLE],
                     capture_output=True, text=True, check=True)
  stdout = [line.strip() for line in p.stdout.split('\n') if line]
  instance_id = stdout[-1].split(':')[-1]
  assert len(instance_id.split()) == 1, instance_id
  return common.CipdInstance(instance_id)


def cipd_version_to_githash(version: common.CipdVersion) -> common.GitHash:
  """Find the git hash for a recipes CIPD instance (whether named ref or ID).

  Sample `cipd describe` output:
  Package:       infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes
  Instance ID:   dv0onkHQ71tjY2cvQiePm-ve1tCfbHfvi40xJWs5EbAC
  Registered by: user:infra-internal-recipe-bundler@chops-service-accounts.iam.gserviceaccount.com
  Registered at: 2022-09-23 13:11:22.569365 -0600 MDT
  Refs:
    prod
    release_2022/09/23-12
  Tags:
    git_revision:1114d30c71229c5cd470df15f863e9ddcfff6fb5
  """
  cmd = ['cipd', 'describe', '-version', version, common.RECIPE_BUNDLE]
  p = subprocess.run(cmd, text=True, capture_output=True, check=True)
  lines = p.stdout.split('\n')
  git_rev_lines = [line for line in lines if 'git_revision' in line]
  assert len(git_rev_lines) >= 1, lines
  git_rev_line = git_rev_lines[0]
  assert git_rev_line.count(':') == 1, git_rev_line
  githash = git_rev_line.strip().split(':')[1]
  assert all(c in string.hexdigits for c in githash), githash
  return common.GitHash(githash)


def determine_cipd_and_git_targets(
    instanceid: Optional[common.CipdInstance] = None
) -> Tuple[common.CipdInstance, common.GitHash]:
  """Find the target CIPD instance (if not provided) and Git hash."""
  if instanceid:
    git_target = cipd_version_to_githash(instanceid)
    cipd_target = instanceid
  else:
    git_target = cipd_version_to_githash(common.CipdInstance('refs/heads/main'))
    cipd_target = _cipd_ref_to_instance_id(
        common.CipdRef(f'git_revision:{git_target}'))
  return (cipd_target, git_target)
