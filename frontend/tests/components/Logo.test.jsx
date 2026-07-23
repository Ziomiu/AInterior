import { it, expect, describe, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

import React from 'react';
import Logo from '../../src/components/ui/Logo';

afterEach(() => {
  cleanup();
});

describe('Logo', () => {
  it('renders the logo image', () => {
    render(<Logo />);

    const icon = screen.getByRole('img', { name: /ainterior/i });

    expect(icon).toBeInTheDocument();
  });

  it('applies a custom className to the image', () => {
    render(<Logo className="custom-class" />);

    expect(screen.getByRole('img', { name: /ainterior/i })).toHaveClass('custom-class');
  });
});
