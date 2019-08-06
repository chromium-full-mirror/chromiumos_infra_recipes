# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for the PUpr generator.

PUpr is a general uprev pipeline that listens for package releases (via LUCI
Scheduler gitiles triggers), generates ebuild uprev CLs for those releases,
and tags the appropriate reviewers. Think of it as the CrOS autoroller.

See go/pupr and go/pupr-generator for rationale and design decisions.
"""

import collections
import urlparse

from PB.chromiumos.common import PackageInfo
from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.recipes.chromeos.generator import GeneratorProperties
from PB.recipes.chromeos.generator import G3OncallRotation
from PB.recipes.chromeos.generator import Reviewer
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (
    triggers as triggers_pb2)

from google.protobuf import json_format


DEPS = [
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'git',
    'naming',
    'oncall',
]

PROPERTIES = GeneratorProperties


def RunSteps(api, properties):
  triggers = api.scheduler.triggers

  with api.step.nest('validate properties') as step:
    if not properties.HasField('package_info'):
      raise ValueError('must set package_info')

    if not properties.reviewers:
      raise ValueError('need at least one reviewer')

    for reviewer in properties.reviewers:
      if reviewer.WhichOneof('identifier') is None:
        raise ValueError('must set reviewer idenifier')

    step.presentation.step_text = 'all properties good'

  with api.step.nest('validate triggers') as step:
    if not triggers:
      raise ValueError('found no scheduler triggers')

    for trigger in triggers:
      if not trigger.HasField('gitiles'):
        raise ValueError('found non-gitiles trigger: %r', trigger)

    step.presentation.step_text = 'all {} triggers good'.format(len(triggers))
    step.presentation.logs['list of triggers'] = map(json_format.MessageToJson,
                                                     triggers)

  package = properties.package_info
  cpv = api.naming.get_package_title(package)

  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context():
    with api.step.nest('try uprev {}'.format(cpv)) as step:
      request = UprevVersionedPackageRequest(
          chroot=api.cros_sdk.chroot,
          package_info=package,
          versions=[
              UprevVersionedPackageRequest.GitRef(
                  repository=urlparse.urlparse(trigger.gitiles.repo).path,
                  ref=trigger.gitiles.ref,
                  revision=trigger.gitiles.revision)
              for trigger in triggers
          ],
      )
      response = api.cros_build_api.PackageService.UprevVersionedPackage(
          request, name='uprev versioned package')

      if not response.modified_ebuilds:
        step.presentation.step_text = 'no new versions for {}'.format(cpv)
        return

    with api.step.nest('commit uprev'):
      ebuilds_by_repository = collections.defaultdict(list)
      for ebuild in response.modified_ebuilds:
        ebuilds_by_repository[api.git.repository_root()].append(ebuild.path)

      for repository, ebuilds in ebuilds_by_repository.iteritems():
        with api.step.nest(
            'commit files in {}'.format(api.path.basename(repository))):
          api.git.add(ebuilds)
          # TODO(evanhernandez): Include version in commit message.
          api.git.commit('automatic uprev for {}'.format(cpv))

  reviewer_users = set()
  with api.step.nest('resolve reviewers'):
    for reviewer in properties.reviewers:
      # If it's just a chromium user, easy peasy.
      if reviewer.HasField('chromium_user'):
        reviewer_users.add(reviewer.chromium_user)
        continue

      # Otherwise we must resolve an oncall rotation.
      rotation = reviewer.g3oncall_rotation
      oncall = api.oncall.status(rotation.name)
      if rotation.position in (G3OncallRotation.PRIMARY,
                               G3OncallRotation.PRIMARY_AND_SECONDARY,
                               G3OncallRotation.UNSPECIFIED):
        reviewer_users.add(oncall.primary)
      if rotation.position in (G3OncallRotation.SECONDARY,
                               G3OncallRotation.PRIMARY_AND_SECONDARY):
        reviewer_users.add(oncall.secondary)


def GenTests(api):
  package = PackageInfo(category='chromeos-base', package_name='chromite')
  properties = json_format.MessageToDict(
      GeneratorProperties(
          package_info=package,
          reviewers=[
              Reviewer(chromium_user='evanhernandez'),
              Reviewer(
                  g3oncall_rotation=G3OncallRotation(
                      name='chromeos-ci-eng',
                      position=G3OncallRotation.PRIMARY_AND_SECONDARY,
                  ),
              ),
          ],
      ),
  )
  gitiles_triggers = [
      triggers_pb2.Trigger(
          id='123',
          gitiles=triggers_pb2.GitilesTrigger(
              repo='chromiumos/chromite',
              ref='refs/heads/master',
              revision='deadbeef',
          ),
      ),
  ]

  yield (api.test('with-uprev') +
         api.properties(**properties) +
         api.scheduler(triggers=gitiles_triggers) +
         api.oncall.status(
             'resolve reviewers.resolve chromeos-ci-eng rotation status'))

  yield api.test('no-package-info') + api.expect_exception('ValueError')

  yield (api.test('no-reviewers') +
         api.properties(package_info=package) +
         api.expect_exception('ValueError'))

  yield (api.test('blank-reviewer') +
         api.properties(package_info=package, reviewers=[{}]) +
         api.expect_exception('ValueError'))

  yield (api.test('no-triggers') +
         api.properties(**properties) +
         api.scheduler(triggers=[]) +
         api.expect_exception('ValueError'))

  yield (api.test('non-gitiles-triggers') +
         api.properties(**properties) +
         api.scheduler(triggers=[
             triggers_pb2.Trigger(id='456', webui=triggers_pb2.WebUITrigger()),
         ]) +
         api.expect_exception('ValueError'))

  yield (api.test('without-uprev') +
         api.properties(**properties) +
         api.scheduler(triggers=gitiles_triggers) +
         api.step_data(
             'try uprev chromeos-base/chromite.uprev versioned package'
             '.read output file',
             api.file.read_raw(content='{}')))
