from __future__ import annotations

from typing import Dict, List, Tuple

# Pack name -> list of (alias_tool, base_tool)
ERP_ALIAS_PACKS: Dict[str, List[Tuple[str, str]]] = {
    # Xero-flavored naming
    "xero": [
        ("xero.create_purchase_order", "erp.create_po"),
        ("xero.get_purchase_order", "erp.get_po"),
        ("xero.list_purchase_orders", "erp.list_pos"),
        ("xero.create_invoice", "erp.submit_invoice"),
        ("xero.get_invoice", "erp.get_invoice"),
        ("xero.list_invoices", "erp.list_invoices"),
        ("xero.post_payment", "erp.post_payment"),
    ],
    # NetSuite-like
    "netsuite": [
        ("netsuite.po.create", "erp.create_po"),
        ("netsuite.po.get", "erp.get_po"),
        ("netsuite.po.list", "erp.list_pos"),
        ("netsuite.invoice.create", "erp.submit_invoice"),
        ("netsuite.invoice.get", "erp.get_invoice"),
        ("netsuite.invoice.list", "erp.list_invoices"),
        ("netsuite.payment.apply", "erp.post_payment"),
    ],
    # Dynamics-like
    "dynamics": [
        ("dynamics.po.create", "erp.create_po"),
        ("dynamics.po.get", "erp.get_po"),
        ("dynamics.po.list", "erp.list_pos"),
        ("dynamics.invoice.create", "erp.submit_invoice"),
        ("dynamics.invoice.get", "erp.get_invoice"),
        ("dynamics.invoice.list", "erp.list_invoices"),
        ("dynamics.payment.post", "erp.post_payment"),
    ],
    # QuickBooks-like
    "quickbooks": [
        ("quickbooks.purchaseorder.create", "erp.create_po"),
        ("quickbooks.purchaseorder.get", "erp.get_po"),
        ("quickbooks.purchaseorder.list", "erp.list_pos"),
        ("quickbooks.invoice.create", "erp.submit_invoice"),
        ("quickbooks.invoice.get", "erp.get_invoice"),
        ("quickbooks.invoice.list", "erp.list_invoices"),
        ("quickbooks.payment.create", "erp.post_payment"),
    ],
}

# CRM alias packs: pack -> list[(alias_tool, base_tool)]
CRM_ALIAS_PACKS: Dict[str, List[Tuple[str, str]]] = {
    # HubSpot-style
    "hubspot": [
        ("hubspot.contacts.create", "crm.create_contact"),
        ("hubspot.contacts.get", "crm.get_contact"),
        ("hubspot.contacts.list", "crm.list_contacts"),
        ("hubspot.companies.create", "crm.create_company"),
        ("hubspot.companies.get", "crm.get_company"),
        ("hubspot.companies.list", "crm.list_companies"),
        ("hubspot.associations.contact_company", "crm.associate_contact_company"),
        ("hubspot.deals.create", "crm.create_deal"),
        ("hubspot.deals.get", "crm.get_deal"),
        ("hubspot.deals.list", "crm.list_deals"),
        ("hubspot.deals.update_stage", "crm.update_deal_stage"),
        ("hubspot.activities.log", "crm.log_activity"),
    ],
    # Salesforce-style (Sales Cloud)
    "salesforce": [
        ("salesforce.contact.create", "crm.create_contact"),
        ("salesforce.contact.get", "crm.get_contact"),
        ("salesforce.contact.list", "crm.list_contacts"),
        ("salesforce.account.create", "crm.create_company"),
        ("salesforce.account.get", "crm.get_company"),
        ("salesforce.account.list", "crm.list_companies"),
        ("salesforce.contact.link_account", "crm.associate_contact_company"),
        ("salesforce.opportunity.create", "crm.create_deal"),
        ("salesforce.opportunity.get", "crm.get_deal"),
        ("salesforce.opportunity.list", "crm.list_deals"),
        ("salesforce.opportunity.update_stage", "crm.update_deal_stage"),
        ("salesforce.activity.log", "crm.log_activity"),
    ],
}
