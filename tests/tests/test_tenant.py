# Copyright 2017 Northern.tech AS
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        https://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
import os
import json

from base64 import urlsafe_b64encode

import pytest

from common import Device, DevAuthorizer, \
    device_auth_req, \
    clean_migrated_db, clean_db, mongo, cli, \
    management_api, device_api

import mockserver
import deviceadm


def get_fake_tenantadm_addr():
    return os.environ.get('FAKE_TENANTADM_ADDR', '0.0.0.0:9999')


class TestMultiTenant:

    def test_auth_req_no_tenantadm(self, management_api, device_api, tenant_foobar):
        d = Device()
        da = DevAuthorizer(tenant_token=tenant_foobar)
        url = device_api.auth_requests_url

        # poke devauth so that device appears, but since tenantadm service is
        # unavailable we'll get 500 in return
        rsp = device_auth_req(url, da, d)
        assert rsp.status_code == 500

        # request failed, so device should not even be listed as known
        TestMultiTenant.verify_tenant_dev_present(management_api, d.identity, tenant_foobar,
                                                  present=False)

    def test_auth_req_fake_tenantadm_invalid_tenant_token(self, management_api, device_api,
                                                          clean_migrated_db):
        d = Device()
        da = DevAuthorizer(tenant_token="bad-token")
        url = device_api.auth_requests_url

        handlers = [
            ('POST', '/api/internal/v1/tenantadm/tenants/verify',
             lambda _: (401, {}, '')),
        ]
        with mockserver.run_fake(get_fake_tenantadm_addr(),
                                handlers=handlers) as fake:
            rsp = device_auth_req(url, da, d)
            assert rsp.status_code == 401

        # request failed, so device should not even be listed as known for the
        # default tenant
        TestMultiTenant.verify_tenant_dev_present(management_api, d.identity, '',
                                                  present=False)

    def test_auth_req_fake_tenantadm_valid_tenant_token(self, management_api, device_api,
                                                        tenant_foobar):
        d = Device()
        da = DevAuthorizer(tenant_token=tenant_foobar)
        url = device_api.auth_requests_url

        handlers = [
            ('POST', '/api/internal/v1/tenantadm/tenants/verify',
             lambda _: (200, {}, {
                 'id': '507f191e810c19729de860ea',
                 'name': 'Acme',
             })),
        ]
        with mockserver.run_fake(get_fake_tenantadm_addr(),
                                handlers=handlers) as fake:
            with deviceadm.run_fake_for_device(d) as fakedevadm:
                rsp = device_auth_req(url, da, d)
                assert rsp.status_code == 401

        # device should be appear in devices listing
        TestMultiTenant.verify_tenant_dev_present(management_api, d.identity, tenant_foobar,
                                                  present=True)

    def test_auth_req_fake_tenantadm_no_tenant_token(self, management_api, device_api,
                                                     clean_migrated_db):
        d = Device()
        # use empty tenant token
        da = DevAuthorizer(tenant_token="")
        url = device_api.auth_requests_url

        rsp = device_auth_req(url, da, d)
        assert rsp.status_code == 401

        TestMultiTenant.verify_tenant_dev_present(management_api, d.identity, '',
                                                  present=False)

    @staticmethod
    def get_device(management_api, identity, token):
        if token:
            dev = management_api.find_device_by_identity(identity,
                                                         Authorization='Bearer '+token)
        else:
            # use default auth
            dev = management_api.find_device_by_identity(identity)
        return dev

    @staticmethod
    def verify_tenant_dev_present(management_api, identity, token, present=False):
        dev = TestMultiTenant.get_device(management_api, identity, token)
        if present:
            assert dev
        else:
            assert not dev


def make_fake_tenant_token(tenant):
    """make_fake_tenant_token will generate a JWT-like tenant token which looks
    like this: 'fake.<base64 JSON encoded claims>.fake-sig'. The claims are:
    issuer (Mender), subject (fake-tenant), mender.tenant (foobar)
    """
    claims = {
        'iss': 'Mender',
        'sub': 'fake-tenant',
        'mender.tenant': tenant,
    }

    # serialize claims to JSON, encode as base64 and strip padding to be
    # compatible with JWT
    enc = urlsafe_b64encode(json.dumps(claims).encode()). \
          decode().strip('==')

    return 'fake.' + enc + '.fake-sig'


@pytest.fixture
@pytest.mark.parametrize('clean_migrated_db', ['foobar'], indirect=True)
def tenant_foobar(request, clean_migrated_db):
    """Fixture that sets up a tenant with ID 'foobar', on top of a clean migrated
    (with tenant support) DB.
    """
    return make_fake_tenant_token('foobar')
