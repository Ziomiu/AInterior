import { it, expect, describe, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom/vitest';

import React from 'react';
import Button from '../../src/components/ui/Button';

afterEach(() => {
  cleanup();
});

describe('Button', () => {
  it('renders the solid dark variant with its label', () => {
    render(<Button>Start Creating</Button>);

    const button = screen.getByRole('button', { name: /start creating/i });

    expect(button).toBeInTheDocument();
    expect(button).toHaveClass('bg-primary', 'text-primary-foreground');
  });

  it('renders an icon alongside the label when provided', () => {
    render(<Button icon="+">New Project</Button>);

    const button = screen.getByRole('button', { name: /new project/i });

    expect(button).toBeInTheDocument();
    expect(screen.getByText('+')).toBeInTheDocument();
  });

  it('does not render an icon wrapper when no icon is provided', () => {
    render(<Button>Start Creating</Button>);

    expect(screen.queryByText('+')).not.toBeInTheDocument();
  });

  it('calls onClick when clicked', async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Start Creating</Button>);

    await user.click(screen.getByRole('button', { name: /start creating/i }));

    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('merges custom className with the default styles', () => {
    render(<Button className="custom-class">Start Creating</Button>);

    expect(screen.getByRole('button')).toHaveClass('custom-class', 'bg-primary');
  });
});
