# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API featuring shared helpers for naming things."""

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipes.chromeos.test_moblab_vm import TestMoblabVmProperties
from PB.recipes.chromeos.test_vm import TestVmProperties

from recipe_engine import recipe_api

from google.protobuf import json_format


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
      return self.get_all_vm_test_title(test)
    elif isinstance(test, self.m.skylab.SkylabResult):
      return self.get_skylab_result_title(test)
    else:
      raise TypeError('Expected Build or SkylabResult,' 'got %s' % type(test))

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

  def get_all_vm_test_title(self, vm_test):
    """Get a string to describe the VM test.

    Args:
      vm_test (Build): The buildbucket build for the VM test.

    Returns:
      str: A string describing the VM test.
    Raises:
      ValueError if name not in vm_test.input.properties.
    """
    all_properties = vm_test.input.properties or vm_test.output.properties
    return all_properties['name']


  def get_vm_test_title(self, vm_test):
    """Get a string to describe the VM test.

    Args:
      vm_test (Build): The buildbucket build for the VM test.

    Returns:
      str: A string describing the VM test.
    """
    all_properties = vm_test.input.properties or vm_test.output.properties
    input_properties = json_format.Parse(
        json_format.MessageToJson(all_properties),
        TestVmProperties(), ignore_unknown_fields=True)
    assert input_properties.name, 'missing name: %r' % input_properties
    return input_properties.name

  def get_moblab_vm_test_title(self, moblab_vm_test):
    """Get a string to describe the VM test.

    Args:
      moblab_vm_test (Build): The buildbucket build for the Moblab VM test.

    Returns:
      str: A string describing the VM test.
    """
    all_properties = (moblab_vm_test.input.properties
                      or moblab_vm_test.output.properties)
    input_properties = json_format.Parse(
        json_format.MessageToJson(all_properties),
        TestMoblabVmProperties(), ignore_unknown_fields=True)
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
