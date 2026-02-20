# Credit Notes

## Overview

| Property | Description |
| --- | --- |
| URL | https://api.xero.com/api.xro/2.0/CreditNotes |
| Methods Supported | POST, PUT, GET, DELETE |
| Description | Allows you to retrieve any credit notes<br>Allows you to add or update draft credit notes<br>Allows you to add approved credit notes<br>Allows you to allocate credit notes to invoices<br>Allows you to delete draft credit notes<br>Allows you to void approved credit notes<br>Allows you to attach files to credit notes<br>Allows you to retrieve history<br>Allows you to add notes<br>To refund credit notes use the payments endpoint |

## GET CreditNotes

Amounts are in the credit note's currency.

The following elements are returned in the CreditNotes response.

| Field | Description |
| --- | --- |
| Type | See Credit Note Types |
| Contact | See Contacts |
| Date | The date the credit note is issued YYYY-MM-DD. If the Date element is not specified then it will default to the current date based on the timezone setting of the organisation |
| Status | See Credit Note Status Codes |
| LineAmountTypes | See Invoice Line Amount Types |
| LineItems | See Invoice Line Items |
| SubTotal | The subtotal of the credit note excluding taxes |
| TotalTax | The total tax on the credit note |
| Total | The total of the Credit Note(subtotal + total tax) |
| CISDeduction | CISDeduction withheld by the contractor to be paid to HMRC on behalf of subcontractor (Available for organisations under UK Construction Industry Scheme) |
| UpdatedDateUTC | UTC timestamp of last update to the credit note |
| CurrencyCode | Currency used for the Credit Note |
| FullyPaidOnDate | Date when credit note was fully paid(UTC format) |
| CreditNoteID | Xero generated identifier (unique within organisations) |
| CreditNoteNumber | ACCRECCREDIT – Unique alpha numeric code identifying credit note.<br>ACCPAYCREDIT – Non-unique alpha numeric code identifying credit note. This value will also display as Reference in the UI. |
| Reference | ACCRECCREDIT only – additional reference number |
| SentToContact | boolean to indicate if a credit note has been sent to a contact via the Xero app. A credit note can only be marked SentToContact if it is in an Awaiting Payment or Paid state. Please ensure you check if you are correctly using SentToContact. Setting it asfalse will mark the credit note unsent. Passing null is OK as the system won't change the credit note. |
| CurrencyRate | For base currency credit notes, has a value of 1. For non-base-currency credit notes, see CurrencyRate meaning. |
| RemainingCredit | The remaining credit balance on the Credit Note |
| Allocations | See Allocations |
| BrandingThemeID | See BrandingThemes |
| HasAttachments | boolean to indicate if a credit note has an attachment |

## Optional parameters for GET CreditNotes

| Field | Description |
| --- | --- |
| Record filter | You can specify an individual record by appending the value to the endpoint, i.e. GET https://.../CreditNotes/{identifier}<br><br>CreditNoteID – The Xero identifier for a Credit Note e.g. 297c2dc5-cc47-4afd-8ec8-74990b8761e9<br><br>CreditNoteNumber – Identifier for Credit Note CN-8743802 |
| Modified After | The ModifiedAfter filter is actually an HTTP header: 'If-Modified-Since'. A UTC timestamp (yyyy-mm-ddThh:mm:ss) . Only credit notes created or modified since this timestamp will be returned e.g. 2009-11-12T00:00:00 |
| Where | Filter by an any element (see Filters) |
| order | Order by any element returned (see Order By) |
| page | 100 credit notes will be returned per call as the default when the page parameter is used by itself e.g. page=1 |
| pageSize | Used with the page parameter. Sets the # of credit notes to be returned per call when the pageSize parameter is used with the page parameter e.g. page=1&pageSize=250. |

### High volume threshold limit

In order to make our platform more stable, we've added a high volume threshold limit for the GET Credit Notes Endpoint.

- Requests that have more than 100k credit notes being returned in the response will be denied
- Requests using unoptimised fields for filtering or ordering that result in more than 100k credit notes will be denied with a 400 response code

Please continue reading to find out how you can use paging and optimise your filtering to ensure your requests are always successful. Be sure to check out the Efficient Data Retrieval page for tips on query optimisation.

### Paging credit notes (recommended)

By using paging all the line item details for each credit note are returned which may avoid the need to retrieve each individual credit note.

More information about retrieving paged resources.

### Optimised filtering using the where parameter

The most common filters have been optimised to ensure performance across organisations of all sizes. We recommend you restrict your filtering to the following optimised parameters.

### Range Operators in Where clauses

Indicated fields also support the range operators: greater than, greater than or equals, less than, less than or equals (>, >=, <, <=).

Range operators can be combined with the AND operator to query a date range. eg where=Date>=DateTime(2020, 01, 01) AND Date<DateTime(2020, 02, 01)

When using individually or combined with the AND operator:

| Field | Operation | Description |
| --- | --- | --- |
| Status | equals | where=Status="PAID" |
| Date | equals, range | where=Date=DateTime(2020, 01, 01)<br>where=Date>DateTime(2020, 01, 01) |
| Reference | equals | where=Reference="CN-0002" |
| Contact.ContactID | equals | where=Contact.ContactID=guid("96988e67-ecf9-466d-bfbf-0afa1725a649") |
| Contact.Name | equals | where=Contact.Name="ABC limited" |
| Contact.ContactNumber | equals | where=Contact.ContactNumber="ID001" |
| Type | equals | where=Type="ACCRECCREDIT" |

#### Example: Retrieve all PAID credit notes on the 1st of January, 2020

```
?where=Status=="PAID" AND Date=DateTime(2020, 01, 01)
```

This would translate to the following URL once encoded.

```
https://api.xero.com/api.xro/2.0/CreditNotes?where=Status%3D%3D%22PAID%22+AND+Date%3DDateTime%282020%2C+01%2C+01%29%0D%0A
```

### Optimised ordering:

The following parameters are optimised for ordering:

- CreditNoteID
- UpdatedDateUTC
- Date

The default order is UpdatedDateUTC ASC, CreditNoteID ASC. Secondary ordering is applied by default using the CreditNoteID. This ensures consistency across pages.

### Example response for GET CreditNotes (without paging)

```
GET https://api.xero.com/api.xro/2.0/CreditNotes
```

```json
{
  "CreditNotes": [
    {
      "Contact": {
        "ContactID": "c6c7b870-bb4d-489a-921e-2f0ee4192ff9",
        "Name": "Test Apply Credit Note"
      },
      "DateString": "2016-12-16T00:00:00",
      "Date": "\/Date(1481846400000+0000)\/",
      "Status": "PAID",
      "LineAmountTypes": "Inclusive",
      "SubTotal": 86.96,
      "TotalTax": 13.04,
      "Total": 100.00,
      "UpdatedDateUTC": "\/Date(1290168061547+0000)\/",
      "CurrencyCode": "NZD",
      "FullyPaidOnDate": "\/Date(1481846400000+0000)\/",
      "Type": "ACCRECCREDIT",
      "CreditNoteID": "aea95d78-ea48-456b-9b08-6bc012600072",
      "CreditNoteNumber": "CN-0002",
      "CurrencyRate": 1.000000,
      "RemainingCredit": 0.00,
      "Allocations": [
        {
          "AllocationID": "b12335f4-a1e5-4431-aeb4-488e5547558e",
          "Amount": 100.00,
          "Date": "\/Date(1481846400000+0000)\/",
          "Invoice": {
            "InvoiceID": "87cfa39f-136c-4df9-a70d-bb80d8ddb975",
            "InvoiceNumber": "INV-0001"
          }
        }
      ]
    }
  ]
}
```

### Example response for retrieving an individual CreditNote

```
GET https://api.xero.com/api.xro/2.0/CreditNotes/7df8949c-b71f-40c0-bbcf-39f2f450f286
```

```json
{
  "CreditNotes": [
    {
      "Contact": {
        "ContactID": "d0cd2c4f-18a0-4f7c-a32a-2db00f29d298",
        "ContactStatus": "ACTIVE",
        "Name": "PC Complete"
        ...
      },
      "DateString": "2017-02-07T00:00:00",
      "Date": "\/Date(1486425600000+0000)\/",
      "DueDate": "\/Date(1486425600000+0000)\/",
      "Status": "PAID",
      "LineAmountTypes": "Exclusive",
      "LineItems": [
        {
          "Description": "Internal DVD drive couldn't be supplied, backorder (Oliver laptop)",
          "UnitAmount": 199.00,
          "TaxType": "INPUT",
          "TaxAmount": 19.90,
          "LineAmount": 199.00,
          "AccountCode": "453",
          "AccountId": "fc8f0c5e-a3dc-4de3-ab8d-37ae0e5d152f",
          "Tracking": [
            {
              "Name": "Region",
              "Option": "North",
              "TrackingCategoryID": "093af706-c2aa-4d97-a4ce-2d205a017eac",
              "TrackingOptionID": "3f05cdf9-246b-46a2-bf6f-441da1b09b89"
            }
          ],
          "Quantity": 1.0000
        }
      ],
      "SubTotal": 199.00,
      "TotalTax": 19.90,
      "Total": 218.90,
      "UpdatedDateUTC": "\/Date(1290777947340+0000)\/",
      "CurrencyCode": "AUD",
      "FullyPaidOnDate": "\/Date(1486425600000+0000)\/",
      "Type": "ACCPAYCREDIT",
      "RemainingCredit": 0.00,
      "Allocations": [
        {
          "AllocationID": "b12335f4-a1e5-4431-aeb4-488e5547558e",
          "Amount": 218.90,
          "Date": "\/Date(1486425600000+0000)\/",
          "Invoice": {
            "InvoiceID": "673dd7cc-beb7-4697-83d4-0c47cb400cc2"
          }
        }
      ],
      "HasAttachments": false,
      "CreditNoteID": "7df8949c-b71f-40c0-bbcf-39f2f450f286",
      "CreditNoteNumber": "03391"
    }
  ]
}
```

## POST CreditNotes

Use this method to create or update a credit note. Amounts are in the credit note's currency.

| Field | Description |
| --- | --- |
| Type | See Credit Note Types |
| Contact | See Contacts |
| Date | The date the credit note is issued YYYY-MM-DD. If the Date element is not specified then it will default to the current date based on the timezone setting of the organisation |
| Status | See Credit Note Status Codes |
| LineAmountTypes | See Invoice Line Amount Types |
| LineItems | See Invoice Line Items |
| CurrencyCode | Currency used for the Credit Note. Defaults to the organisation's base currency. |
| CreditNoteNumber | ACCRECCREDIT – Unique alpha numeric code identifying credit note (when missing will auto-generate from your Organisation Invoice Settings)<br>ACCPAYCREDIT – non-unique alpha numeric code identifying credit note. This value will also display as Reference in the UI. |
| Reference | ACCRECCREDIT only – additional reference number |
| SentToContact | boolean to indicate if a credit note has been sent to a contact via the Xero app (currently read only) |
| CurrencyRate | For how and when to set, see our multicurrency guide. |
| BrandingThemeID | See BrandingThemes |

### SummarizeErrors

If you are entering many credit notes in a single API call then we recommend you utilise our new response format that shows validation errors for each invoice. The new response messages for validating bulk API calls would mean a breaking change so to utilise this functionality you'll need to append ?SummarizeErrors=false to the end of your API calls e.g. POST /api.xro/2.0/CreditNotes?SummarizeErrors=false

### Example of minimum elements required to add a new draft credit note with no line items

```
POST https://api.xero.com/api.xro/2.0/CreditNotes
```

```json
{
  "Type": "ACCPAYCREDIT",
  "Contact": {
    "ContactID": "eaa28f49-6028-4b6e-bb12-d8f6278073fc"
  }
}
```

### Example of a draft credit note with enough detail to be approved once it's been created.

```
POST https://api.xero.com/api.xro/2.0/CreditNotes
```

```json
{
  "Type": "ACCPAYCREDIT",
  "Contact": {
    "ContactID": "eaa28f49-6028-4b6e-bb12-d8f6278073fc"
  },
  "Date": "2009-03-29",
  "LineAmountTypes": "Exclusive",
  "LineItems": [
    {
      "Description": "MacBook - White",
      "Quantity": 1.0000,
      "UnitAmount": 1995.00,
      "AccountCode": "720"
    }
  ]
}
```

### Example of a creating an approved credit note

```
POST https://api.xero.com/api.xro/2.0/CreditNotes
```

```json
{
  "Type": "ACCPAYCREDIT",
  "Status": "AUTHORISED",
  "Contact": {
    "ContactID": "eaa28f49-6028-4b6e-bb12-d8f6278073fc"
  },
  "Date": "2009-03-29",
  "LineAmountTypes": "Exclusive",
  "LineItems": [
    {
      "Description": "MacBook - White",
      "Quantity": 1.0000,
      "UnitAmount": 1995.00,
      "AccountCode": "720"
    }
  ]
}
```

## Uploading an Attachment

You can upload up to 10 attachments (each up to 25mb in size) per credit note, once the credit note has been created in Xero. To do this you'll need to know the ID of the credit note which you'll use to construct the URL when POST/PUTing a byte stream containing the attachment file. See the Attachments page for more details.

### Example request to upload an attachment

```
POST https://api.xero.com/api.xro/2.0/CreditNotes/f0ec0d8c-6fce-4330-bb3b-8306278c6fd8/Attachments/image.png
```

```
Headers:
Authorization: Bearer...
Content Type: image/png
Content-Length: 10293

Body:
{RAW-IMAGE-CONTENT}
```

## PUT CreditNotes

### Creating CreditNotes

The PUT method can be used to create CreditNotes or allocate CreditNotes to outstanding Invoices.

Creating a CreditNote via PUT uses the same request format as via POST – please refer to the above examples.

### Allocating CreditNotes

The elements required to allocate a credit note to an invoice

| Field | Description |
| --- | --- |
| Invoice | The invoice the credit note is being allocated against |
| AppliedAmount/Amount | AppliedAmount if using XML and Amount if using JSON. The amount being applied to the invoice. |
| Date | The date the credit note is applied YYYY-MM-DD (read-only). This will be the latter of the invoice date and the credit note date. |

Credit notes must have a Status of AUTHORISED to be available for allocation.

You cannot create and allocate a credit note in a single call. The create and allocation must be done in two separate calls

Note: Currently applying 'Allocations' cannot be tested through the API Explorer.

#### An example request to allocate $60.50 from an ACCREC credit note to an outstanding ACCREC invoice for the same contact. Note the Request URL needs to specify the credit note that you are allocating

```
PUT https://api.xero.com/api.xro/2.0/CreditNotes/7df8949c-b71f-40c0-bbcf-39f2f450f286/Allocations
```

```json
{
  "Amount": 60.50,
  "Invoice": {
    "InvoiceID": "f5832195-5cd3-4660-ad3f-b73d9c64f263"
  }
}
```

## Retrieving History

View a summary of the actions made by all users to the credit note. See the History and Notes page for more details.

### Example of retrieving a credit note's history

```
GET https://api.xero.com/api.xro/2.0/CreditNotes/{Guid}/History
```

```json
{
  "HistoryRecords": [
     {
       "Changes": "Updated",
       "DateUTCString": "2018-02-28T21:02:11",
       "DateUTC": "\/Date(1519851731990+0000)\/",
       "User": "System Generated",
       "Details": "Received through the Xero API from ABC Org"
     },
     {
       "Changes": "Created",
       "DateUTCString": "2018-02-28T21:01:29",
       "DateUTC": "\/Date(1519851689297+0000)\/",
       "User": "Mac Haag",
       "Details": "INV-0041 to ABC Furniture for 100.00."
     }
     ...
  ]
}
```

## Add Notes to a Credit Note

Add a note which will appear in the history against a credit note. See the History and Notes page for more details.

### Example of creating a note against a credit note

```
PUT https://api.xero.com/api.xro/2.0/CreditNotes/{Guid}/History
```

```json
{
  "HistoryRecords": [
    {
      "Details": "Note added by your favourite app!"
    }
    ...
  ]
}
```

## DELETE CreditNotes

### Deleting CreditNotes Allocations

The DELETE method can be used to delete CreditNotes allocations. Note the Request URL needs to specify the allocation ID. You can obtain it from the GET request.

```
DELETE https://api.xero.com/api.xro/2.0/CreditNotes/{CreditNoteID}/Allocations/{AllocationID}
```

### Example response for deleting CreditNotes allocation

```json
{
  "AllocationID": "b12335f4-a1e5-4431-aeb4-488e5547558e",
  "Date": "\/Date(1481846400000+0000)\/",
  "Invoice": {
    "InvoiceID": "f5832195-5cd3-4660-ad3f-b73d9c64f263"
  },
  "IsDeleted": true
}
```
