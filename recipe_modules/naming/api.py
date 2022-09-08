# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API featuring shared helpers for naming things."""

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipes.chromeos.tast_vm import TastVmProperties

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure


class NamingApi(recipe_api.RecipeApi):
  """A module with helpers for naming things."""

  def get_build_title(self, build):
    """Get a string to describe the build.

    Args:
      build (Build): The build to describe.

    Returns:
      str: A string describing the build.
    """
    return build.builder.builder

  def get_test_title(self, test):
    """Get a string to describe the test.

    Args:
      test (SkylabResult|Build): The test in question.

    Returns:
      A str describing the test.
    """
    if isinstance(test, build_pb2.Build):
      return self.get_vm_test_title(test)
    elif isinstance(test, self.m.skylab.SkylabResult):
      return self.get_skylab_result_title(test)
    else:
      raise StepFailure('Expected Build or SkylabResult,' 'got %s' % type(test))

  def get_hw_test_title(self, hw_test):
    """Get a string to describe the HW test.

    Args:
      hw_test (HwTest): The HW test in question.

    Returns:
      str: The HW test title.
    """
    return hw_test.common.display_name

  def get_skylab_task_title(self, skylab_task):
    """Get a string to describe the Skylab task.

    Args:
      skylab_task (SkylabTask): The Skylab task in question.

    Returns:
      str: The Skylab task title.
    """
    return self.get_hw_test_title(skylab_task.test)

  def get_skylab_result_title(self, skylab_result):
    """Get a string to describe the HW test.

    Args:
      skylab_result (SkylabResult): The Skylab result in question.

    Returns:
      str: The HW test title.
    """
    return self.get_skylab_task_title(skylab_result.task)

  def get_vm_test_title(self, vm_test):
    """Get a string to describe the VM test.

    Args:
      vm_test (Build): The buildbucket build for the VM test.

    Returns:
      str: A string describing the VM test.
    """
    all_properties = vm_test.input.properties or vm_test.output.properties
    input_properties = json_format.Parse(
        json_format.MessageToJson(all_properties), TastVmProperties(),
        ignore_unknown_fields=True)
    assert input_properties.name, 'missing name: %r' % input_properties
    return input_properties.name

  def get_commit_title(self, commit):
    """Get a string to describe the commit.

    This is typically the first line of the commit message.

    Args:
      commit (Commit): The commit in question. See recipe_modules/git/api.py

    Returns:
      str: The commit title.
    """
    lines = [l.strip() for l in commit.message.splitlines() if l.strip()]
    assert lines, 'unexpected empty commit message: %s' % commit.message
    return lines[0]

  def get_package_title(self, package):
    """Get a string to describe the package.

    Args:
      package (PackageInfo): The package in question.

    Returns:
      str: The package title.
    """
    title = '{}/{}'.format(package.category, package.package_name)
    if package.version:
      title = '{}-{}'.format(title, package.version)
    return title

  @staticmethod
  def get_paygen_build_title(build_id, paygen_request_dicts):
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
    elif len(paygen_request_dicts) == 0:
      return '%s | No paygen requests' % build_id

    image_types = [title.split(' | ')[0] for title in gen_req_titles]
    image_types_without_suffices = [
        img_type.split('(')[0].strip() for img_type in image_types
    ]
    if all([
        img_type == image_types_without_suffices[0]
        for img_type in image_types_without_suffices
    ]):
      image_type_part = '%dx %s' % (len(paygen_request_dicts),
                                    image_types_without_suffices[0])
    else:
      image_type_part = '%d payloads, various image types' % len(
          paygen_request_dicts)

    versions = [title.split(' | ')[1] for title in gen_req_titles]
    full_or_deltas = [version.split()[0] for version in versions]
    if all([version == versions[0] for version in versions]):
      version_part = versions[0]
    elif all([fod == full_or_deltas[0] for fod in full_or_deltas]):
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

    def _get_img_version(image_field_name):
      """Get an image version from the request dict."""
      return req.get(image_field_name,
                     {}).get('build', {}).get('version', 'unknown-version')

    def _get_img_channel(image_field_name):
      """Get an image channel from the request dict."""
      return req.get(image_field_name,
                     {}).get('build', {}).get('channel', 'unknown-channel')

    def _get_img_type(image_field_name):
      """Get an image type from the request dict."""
      return req.get(image_field_name, {}).get('imageType', 'unknown-type')

    def _get_delta_string(image_field_name, target_version):
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
