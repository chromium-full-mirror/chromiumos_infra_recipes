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

import urlparse

from PB.chromiumos.common import PackageInfo
from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.recipes.chromeos.generator import GeneratorProperties
from PB.go.chromium.org.luci.scheduler.api.scheduler.v1 import (
    triggers as triggers_pb2)

from google.protobuf import json_format


DEPS = [
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'naming',
]

PROPERTIES = GeneratorProperties


def RunSteps(api, properties):
  triggers = api.scheduler.triggers

  with api.step.nest('validate properties') as step:
    if not properties.HasField('package_info'):
      raise ValueError('must set package_info')
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


def GenTests(api):
  properties = json_format.MessageToDict(
      GeneratorProperties(
          package_info=PackageInfo(
              category='chromeos-base',
              package_name='chromite',
          ),
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

  yield api.test('no-package-info') + api.expect_exception('ValueError')

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

  yield (api.test('with-uprev') +
         api.properties(**properties) +
         api.scheduler(triggers=gitiles_triggers))
