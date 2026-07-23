import '@testing-library/jest-dom/vitest';
import userEvent from '@testing-library/user-event';
import { render, screen, cleanup } from '@testing-library/react';
import { it, expect, describe, vi, afterEach } from 'vitest';

import axios from 'axios';
import { store } from '../../src/store';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { toaster } from '../../src/components/ui/toaster';
import AuthModal from '../../src/components/AuthModal';
import { AuthModalProvider, useAuthModal } from '../../src/context/AuthModalContext';

vi.spyOn(toaster, 'create');
vi.mock('axios');

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function Harness({ mode }) {
  const { openLogin, openRegister } = useAuthModal();
  return (
    <>
      <button onClick={mode === 'register' ? openRegister : openLogin}>open modal</button>
      <AuthModal />
    </>
  );
}

const renderModal = async (mode) => {
  render(
    <Provider store={store}>
      <MemoryRouter>
        <AuthModalProvider>
          <Harness mode={mode} />
        </AuthModalProvider>
      </MemoryRouter>
    </Provider>
  );

  const user = userEvent.setup();
  await user.click(screen.getByText('open modal'));
  return user;
};

describe('AuthModal - login', () => {
  it('renders the login form', async () => {
    await renderModal('login');

    expect(screen.getByRole('heading', { name: 'Login' })).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Login' })).toBeInTheDocument();
  });

  it('logs in successfully with correct credentials', async () => {
    const user = await renderModal('login');

    await user.type(screen.getByLabelText('Email'), 'john.doe@example.com');
    await user.type(screen.getByLabelText('Password'), 'johndoe123');

    axios.post.mockResolvedValueOnce({
      data: {
        access_token: 'example-token',
        first_name: 'John',
        last_name: 'Doe',
        email: 'john.doe@example.com',
        role: 'user',
      },
    });

    await user.click(screen.getByRole('button', { name: 'Login' }));

    expect(axios.post).toHaveBeenCalledWith('/api/auth/login', {
      email: 'john.doe@example.com',
      password: 'johndoe123',
    });

    expect(toaster.create).toHaveBeenCalledWith({
      title: 'Logged in successfully',
      status: 'success',
    });
  });

  it('fails to log in with incorrect credentials', async () => {
    const user = await renderModal('login');

    await user.type(screen.getByLabelText('Email'), 'john.doe@example.com');
    await user.type(screen.getByLabelText('Password'), 'johndoe123');

    axios.post.mockRejectedValueOnce({ response: { data: {} } });

    await user.click(screen.getByRole('button', { name: 'Login' }));

    expect(toaster.create).toHaveBeenCalledWith({
      title: 'Login failed',
      description: 'Login failed. Please check your credentials and try again.',
      status: 'error',
    });
  });

  it('rejects submission when fields are missing', async () => {
    const user = await renderModal('login');

    await user.type(screen.getByLabelText('Password'), 'johndoe123');
    await user.click(screen.getByRole('button', { name: 'Login' }));

    expect(axios.post).not.toHaveBeenCalled();
    expect(toaster.create).toHaveBeenCalledWith({
      title: 'Missing fields',
      description: 'Please fill in all the fields.',
      status: 'warning',
    });
  });

  it('rejects submission with an invalid email', async () => {
    const user = await renderModal('login');

    await user.type(screen.getByLabelText('Email'), 'john.doe%example.com');
    await user.type(screen.getByLabelText('Password'), 'johndoe123');
    await user.click(screen.getByRole('button', { name: 'Login' }));

    expect(axios.post).not.toHaveBeenCalled();
    expect(toaster.create).toHaveBeenCalledWith({
      title: 'Invalid email',
      description: 'Please enter a valid email address.',
      status: 'error',
    });
  });

  it('switches to the sign up form', async () => {
    const user = await renderModal('login');

    await user.click(screen.getByRole('button', { name: 'Sign up' }));

    expect(screen.getByRole('heading', { name: 'Sign Up' })).toBeInTheDocument();
  });

  it('closes when the close button is clicked', async () => {
    const user = await renderModal('login');

    await user.click(screen.getByRole('button', { name: 'Close' }));

    expect(screen.queryByRole('heading', { name: 'Login' })).not.toBeInTheDocument();
  });
});

describe('AuthModal - sign up', () => {
  it('renders the sign up form', async () => {
    await renderModal('register');

    expect(screen.getByRole('heading', { name: 'Sign Up' })).toBeInTheDocument();
    expect(screen.getByLabelText('First Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Last Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign Up' })).toBeInTheDocument();
  });

  it('registers successfully with correct details', async () => {
    const user = await renderModal('register');

    await user.type(screen.getByLabelText('First Name'), 'John');
    await user.type(screen.getByLabelText('Last Name'), 'Doe');
    await user.type(screen.getByLabelText('Email'), 'john.doe@example.com');
    await user.type(screen.getByLabelText('Password'), 'johndoe123');

    axios.post
      .mockResolvedValueOnce({ data: { message: 'User registered successfully', user_id: '2137' } })
      .mockResolvedValueOnce({
        data: {
          access_token: 'example-token',
          first_name: 'John',
          last_name: 'Doe',
          email: 'john.doe@example.com',
          role: 'user',
        },
      });

    await user.click(screen.getByRole('button', { name: 'Sign Up' }));

    expect(axios.post).toHaveBeenNthCalledWith(1, '/api/auth/register', {
      first_name: 'John',
      last_name: 'Doe',
      email: 'john.doe@example.com',
      password: 'johndoe123',
      role: 'user',
    });

    expect(axios.post).toHaveBeenNthCalledWith(2, '/api/auth/login', {
      email: 'john.doe@example.com',
      password: 'johndoe123',
    });

    expect(toaster.create).toHaveBeenCalledWith({
      title: 'Account created!',
      status: 'success',
    });
  });

  it('rejects submission when fields are missing', async () => {
    const user = await renderModal('register');

    await user.type(screen.getByLabelText('Email'), 'jane.doe@example.com');
    await user.type(screen.getByLabelText('Password'), 'janedoe123');
    await user.click(screen.getByRole('button', { name: 'Sign Up' }));

    expect(axios.post).not.toHaveBeenCalled();
    expect(toaster.create).toHaveBeenCalledWith({
      title: 'Missing fields',
      description: 'Please fill in all the fields.',
      status: 'warning',
    });
  });

  it('does not register when the email already exists', async () => {
    axios.post.mockRejectedValueOnce({ response: { data: { detail: 'Email already registered' } } });

    const user = await renderModal('register');

    await user.type(screen.getByLabelText('First Name'), 'Jane');
    await user.type(screen.getByLabelText('Last Name'), 'Doe');
    await user.type(screen.getByLabelText('Email'), 'janedoe@example.com');
    await user.type(screen.getByLabelText('Password'), 'janedoe123');

    await user.click(screen.getByRole('button', { name: 'Sign Up' }));

    expect(axios.post).toHaveBeenNthCalledWith(1, '/api/auth/register', {
      first_name: 'Jane',
      last_name: 'Doe',
      email: 'janedoe@example.com',
      password: 'janedoe123',
      role: 'user',
    });

    expect(toaster.create).toHaveBeenCalledWith({
      title: 'Registration failed',
      description: 'An account with this email already exists.',
      status: 'error',
    });
  });

  it('switches back to the login form', async () => {
    const user = await renderModal('register');

    await user.click(screen.getByRole('button', { name: 'Login' }));

    expect(screen.getByRole('heading', { name: 'Login' })).toBeInTheDocument();
  });
});
