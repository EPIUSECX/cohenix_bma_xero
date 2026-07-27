# Disclaimer

**Last updated: 2026-07-27 · Applies to: Xero Integration for ERPNext (the "Software"), all versions**

## 1. Beta software

The Software is released in **Beta**. It is under active development, may
contain defects, and its behavior may change between releases. Beta status is
not a formality: the Software synchronizes financial records between two live
accounting systems, and a defect, misconfiguration, or interrupted sync run can
create, modify, overwrite, or delete accounting data in **ERPNext, Xero, or
both**.

## 2. No warranty

THE SOFTWARE IS PROVIDED **"AS IS"**, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, ACCURACY, RELIABILITY, AND NON-INFRINGEMENT.
NO ORAL OR WRITTEN INFORMATION OR ADVICE GIVEN BY THE AUTHORS, PUBLISHERS, OR
THEIR REPRESENTATIVES CREATES ANY WARRANTY.

## 3. Limitation of liability

TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL THE
AUTHORS, COPYRIGHT HOLDERS, PUBLISHERS, OR DISTRIBUTORS OF THE SOFTWARE BE
LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY — WHETHER IN AN ACTION OF
CONTRACT, TORT, OR OTHERWISE — ARISING FROM, OUT OF, OR IN CONNECTION WITH THE
SOFTWARE OR ITS USE, INCLUDING WITHOUT LIMITATION:

- **loss, corruption, overwriting, or destruction of data** in ERPNext, Xero,
  or any connected system — expressly including losses caused by a failed,
  interrupted, or misconfigured test or synchronization run performed against a
  live Xero organisation or a production ERPNext site;
- loss of profits, revenue, business, goodwill, or anticipated savings;
- business interruption or the cost of substitute software or services;
- accounting, audit, tax, or regulatory consequences of inaccurate or missing
  records, and the cost of reconstructing or re-reconciling data;
- any indirect, incidental, special, consequential, exemplary, or punitive
  damages, even if advised of the possibility of such damages.

## 4. Your responsibilities

Using the Software constitutes acceptance of this disclaimer and of your
responsibility to operate it safely. In particular, you are responsible for:

1. **Testing on non-live systems first.** Complete the staged rollout described
   in the [README](README.md#safe-rollout--read-before-connecting): a non-live
   Xero organisation (e.g. the Xero Demo Company) with a test ERPNext site,
   then inbound-only sync, and only then full bidirectional sync.
2. **Backups.** Maintain current backups of your ERPNext site
   (`bench --site <site> backup`) and exports of your Xero data before enabling
   or changing any sync configuration, and at regular intervals thereafter.
3. **Verification.** Reviewing account mappings, tax mappings, currencies, and
   synchronized figures for correctness. The Software automates data transfer;
   it does not replace accounting review or professional advice.
4. **Access control.** Restricting the Xero Settings doctype, sync dashboard,
   and the System Manager / Xero Integration Manager roles to trusted operators.
5. **Compliance.** Ensuring your use of the Software, and the data it
   transfers, complies with the laws, accounting standards, and data-protection
   rules that apply to you.

## 5. Not professional advice

Nothing in the Software or its documentation constitutes accounting, tax,
legal, or other professional advice. Consult a qualified professional for
advice on your specific circumstances.

## 6. Third-party services and trademarks

The Software connects to the Xero API, a third-party service whose behavior,
availability, and terms are outside the authors' control. You are responsible
for complying with Xero's terms of use and developer terms.

**Xero** is a trademark of Xero Limited. This Software is an independent
integration and is **not affiliated with, endorsed by, or supported by Xero
Limited**. ERPNext and Frappe are trademarks of their respective owners.

## 7. License

The Software is licensed under the MIT License (see [license.txt](license.txt)).
This disclaimer supplements — and to the extent permitted by law extends — the
warranty disclaimer and liability limitation contained in that license. If any
provision of this disclaimer is held unenforceable, the remaining provisions
remain in effect.
