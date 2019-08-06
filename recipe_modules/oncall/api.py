# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with g3oncall."""

import collections

from recipe_engine import recipe_api

USERNAME_KEY = 'person'


class OncallApi(recipe_api.RecipeApi):
  """A module for support tool steps."""

  # Describes a g3oncall rotation
  #
  # Fields:
  #   primary (str): LDAP of primary oncall.
  #   secondary (str): LDAP of secondary oncall.
  RotationStatus = collections.namedtuple('RotationStatus',
                                          ['primary', 'secondary'])

  def status(self, rotation, step_name=None):
    """Get the status for a given oncall rotation.

    Args:
      rotation (str): The name of the rotation.
      step_name (str): Optional step name.

    Returns:
      RotationStatus: The current status for the rotation.
    """
    step_name = step_name or 'resolve {} rotation status'.format(rotation)
    with self.m.step.nest(step_name) as step:
      status_url = 'https://oncall.corp.google.com/{}/json'.format(rotation)
      response = self.m.url.get_json(
          status_url, step_name='fetch rotation status json', log=True)
      response.raise_on_error()
      status = response.output

      # Perform rudimentary validations.
      if not isinstance(status, list):
        raise ValueError('expected json list, got {}'.format(type(status)))
      if len(status) != 2:
        raise ValueError(
            'expected exactly 2 elements in json list, got {}'.format(status))
      for weekly in status:
        if USERNAME_KEY not in weekly:
          raise ValueError('expected username key "{}" in json response'.format(
              USERNAME_KEY))

      return self.RotationStatus(primary=status[0][USERNAME_KEY],
                                 secondary=status[1][USERNAME_KEY])
