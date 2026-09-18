"""Reviewed passages required by the authored reserve, not just topic keywords.

A source containing the word 'barcode' is not sufficient evidence for a price
lookup. Preserve the passages supporting the actual mechanism and its scope.
"""
PASSAGES = {
    'gps': ['Satellite signal blockage due to buildings, bridges, trees, etc.',
            'Signals reflected off buildings or walls ("multipath")'],
    'bluetooth': ['This allows devices to adapt to the RF environment they find themselves operating in and to avoid channels experiencing excessive levels of interference.'],
    'dns': ['DNS translates the domain name that you type in the browser',
            'DNS lookups are performed by dedicated servers called DNS resolvers.',
            'The IP address identifies the server where the website data is stored, allowing the browser to contact the server and load the page.'],
    'roundabout': ['curved approaches that reduce vehicle speed, entry yield control that gives right-of-way to circulating traffic'],
    'baggage': ['a baggage destination tag on your luggage and will give you the bag identification tag (i.e., a label with a barcode)'],
    'screening': ['The majority of checked baggage is screened without the need for a physical bag search.',
                  'If your property is physically inspected, TSA will place a notice of baggage inspection inside your bag.'],
    'unit': ['Unit prices show you how much different products would cost if they were sold in packs of the same weight or volume.'],
    'barcode': ['The barcode represents the number that simply identifies the item uniquely.',
                'All the information about a product is held in a computer database.',
                'By scanning the barcode, this information (including the description and price) may be retrieved from the database.',
                'The only exception is the specialist numbering system devised for Retail Variable Measure Trade Items and money-off coupon numbers that include the price of the item or value of the coupon.'],
    'payment': ['A one-time use security code is generated for every transaction to safeguard against fraud.'],
}
