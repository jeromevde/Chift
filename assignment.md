Hello Jerome,

Désolé pour l'envoi tardif. Voici le test (en anglais):

As you know, Chift offers a unified API. Here is our documentation for our "invoicing" vertical here: https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-contact

The goal of the technical exercise would be to implement a POC (preferably in Python) that would handle automatically generating the code for a connector based on the connector's documentation, and automatically doing the mapping to our unified documentation for a few endpoints.

Concretely:

Connector: https://www.hyperline.co/ (you can create a free account)
They have a well-documented API and an OpenAPI format
Your connector generator must implement these endpoints:

https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-contact
https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-contacts
https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-invoice
https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-invoices

Think how the framework you build can be reused for other connectors
Tu en penses quoi?

Thanks,

Henry