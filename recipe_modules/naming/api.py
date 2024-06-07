# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API featuring shared helpers for naming things."""

import re
from typing import Dict, List, Union

from PB.chromiumos import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.testplans.target_test_requirements_config import HwTestCfg
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure
from RECIPE_MODULES.chromeos.git.api import Commit
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabResult
from RECIPE_MODULES.chromeos.skylab_results.structs import SkylabTask


class NamingApi(recipe_api.RecipeApi):
  """A module with helpers for naming things."""

  @staticmethod
  def get_build_title(build: build_pb2.Build) -> str:
    """Get a string to describe the build.

    Args:
      build: The build to describe.

    Returns:
      A string describing the build.
    """
    return build.builder.builder

  def get_test_title(self, test: Union[SkylabResult, build_pb2.Build]):
    """Get a string to describe the test.

    Args:
      test: The test in question.

    Returns:
      A str describing the test.
    """
    return self.get_skylab_result_title(test)

  @staticmethod
  def get_hw_test_title(hw_test: HwTestCfg.HwTest) -> str:
    """Get a string to describe the HW test.

    Args:
      hw_test: The HW test in question.

    Returns:
      The HW test title.
    """
    return hw_test.common.display_name

  def get_skylab_task_title(self, skylab_task: SkylabTask) -> str:
    """Get a string to describe the Skylab task.

    Args:
      skylab_task: The Skylab task in question.

    Returns:
      The Skylab task title.
    """
    return self.get_hw_test_title(skylab_task.test)

  def get_skylab_result_title(self, skylab_result: SkylabResult) -> str:
    """Get a string to describe the HW test.

    Args:
      skylab_result: The Skylab result in question.

    Returns:
      The HW test title.
    """
    return self.get_skylab_task_title(skylab_result.task)

  @staticmethod
  def get_commit_title(commit: Commit) -> str:
    """Get a string to describe the commit.

    This is typically the first line of the commit message.

    Args:
      commit: The commit in question. See recipe_modules/git/api.py

    Returns:
      The commit title.
    """
    lines = [l.strip() for l in commit.message.splitlines() if l.strip()]
    assert lines, 'unexpected empty commit message: %s' % commit.message
    return lines[0]

  @staticmethod
  def get_package_title(package: common_pb2.PackageInfo) -> str:
    """Get a string to describe the package.

    Args:
      package: The package in question.

    Returns:
      The package title.
    """
    title = '{}/{}'.format(package.category, package.package_name)
    if package.version:
      title = '{}-{}'.format(title, package.version)
    return title

  @staticmethod
  def get_paygen_build_title(build_id: int,
                             paygen_request_dicts: List[Dict]) -> str:
    """Get a presentation name for a build running a batch of PaygenRequests.

    Args:
      build_id (int): The ID of the Paygen build being run.
      paygen_request_dicts (List[dict]): Dicts representing a batch of
        PaygenRequests being run by a single Paygen builder.

    Returns:
      A string providing helpful info about the paygens being run.
    """
    gen_req_titles = [
        NamingApi.get_generation_request_title(
            paygen_request.get('generation_request', {}))
        for paygen_request in paygen_request_dicts
    ]
    if len(paygen_request_dicts) == 1:
      return '%s | %s' % (build_id, gen_req_titles[0])
    if len(paygen_request_dicts) == 0:
      return '%s | No paygen requests' % build_id

    image_types = [title.split(' | ')[0] for title in gen_req_titles]
    image_types_without_suffices = [
        img_type.split('(')[0].strip() for img_type in image_types
    ]
    if all(img_type == image_types_without_suffices[0]
           for img_type in image_types_without_suffices):
      image_type_part = '%dx %s' % (len(paygen_request_dicts),
                                    image_types_without_suffices[0])
    else:
      image_type_part = '%d payloads, various image types' % len(
          paygen_request_dicts)

    versions = [title.split(' | ')[1] for title in gen_req_titles]
    full_or_deltas = [version.split()[0] for version in versions]
    if all(version == versions[0] for version in versions):
      version_part = versions[0]
    elif all(fod == full_or_deltas[0] for fod in full_or_deltas):
      version_part = '%s (various versions)' % full_or_deltas[0]
    else:
      version_part = 'Some full, some delta'
    return '%s | %s | %s' % (build_id, image_type_part, version_part)

  @staticmethod
  def get_generation_request_title(req):
    """Get a presentation name for a single GenerationRequest.

    Args:
      req (dict): Dict representing a GenerationRequest proto, containing a
        single payload to be created.

    Returns:
      A string providing helpful info about that payload.
    """

    def _get_img_version(image_field_name: str) -> str:
      """Get an image version from the request dict."""
      return req.get(image_field_name,
                     {}).get('build', {}).get('version', 'unknown-version')

    def _get_img_channel(image_field_name: str) -> str:
      """Get an image channel from the request dict."""
      return req.get(image_field_name,
                     {}).get('build', {}).get('channel', 'unknown-channel')

    def _get_img_type(image_field_name: str) -> str:
      """Get an image type from the request dict."""
      return req.get(image_field_name, {}).get('imageType', 'unknown-type')

    def _get_delta_string(image_field_name: str, target_version: str) -> str:
      """Get the string representation of a delta for a given image type."""
      source_version = _get_img_version(image_field_name)
      label = 'Delta'
      if source_version == target_version:
        label += '-N2N'
      return '%s (%s-%s)' % (label, source_version, tgt_version)

    tgt_version = ''
    if req.get('tgtDlcImage', {}):
      image_type_part = 'DLC (%s) %s' % (req['tgtDlcImage'].get(
          'dlcId', ''), _get_img_channel('tgtDlcImage'))
      tgt_version = _get_img_version('tgtDlcImage')
    elif req.get('tgtSignedImage', {}):
      image_type_part = 'Signed %s %s' % (_get_img_type('tgtSignedImage'),
                                          _get_img_channel('tgtSignedImage'))
      tgt_version = _get_img_version('tgtSignedImage')
    elif req.get('tgtUnsignedImage', {}):
      image_type_part = 'Unsigned %s %s' % (_get_img_type(
          'tgtUnsignedImage'), _get_img_channel('tgtUnsignedImage'))
      tgt_version = _get_img_version('tgtUnsignedImage')
    else:
      raise StepFailure('No tgt image in gen req: %s' % str(req))
    if req.get('minios', False):
      image_type_part += ', minios'
    if req.get('fullUpdate', False):
      version_part = 'Full (%s)' % tgt_version
    elif req.get('srcDlcImage', {}):
      version_part = _get_delta_string('srcDlcImage', tgt_version)
    elif req.get('srcSignedImage', {}):
      version_part = _get_delta_string('srcSignedImage', tgt_version)
    elif req.get('srcUnsignedImage', {}):
      version_part = _get_delta_string('srcUnsignedImage', tgt_version)
    else:
      version_part = 'No src image found (?-%s)' % tgt_version
    return '%s | %s' % (image_type_part, version_part)

  @staticmethod
  def get_snapshot_builder_name(cq_builder_name: str) -> str:
    """Converts a cq builder name to matching snapshot builder name.

    For example, 'amd64-generic-cq' -> 'amd64-generic-snapshot' or
    'amd64-generic-slim-cq' -> 'amd64-generic-snapshot'.
    """
    return re.sub('(-slim)?-cq$', '-snapshot', cq_builder_name)
