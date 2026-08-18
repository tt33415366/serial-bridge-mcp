# Abort in-flight Exec when leaving Bridge Mode

If the Operator switches to CRT Mode while an Exec is capturing, the Hub aborts that Exec immediately (error, optional partial capture) and then releases the ports. Rejected: finishing the Exec first, or blocking the mode switch until the queue drains — port ownership changes must win.
